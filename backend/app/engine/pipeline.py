"""Оркестрация расчёта: конвейер «файл вошёл — результат вышел» (Спринт 2).

  загрузка → граф сети → кластеры ОКС → точки врезки → маршруты A*
  → постобработка → диаметры/предельные длины → реконструкция →
  стоимость → выходной GeoJSON.

Частичный результат (§2.9): ОКС/кластер, для которого не нашлось
точки врезки или маршрута, не роняет расчёт — попадает в перечень
unconnected с причиной, остальное считается дальше.
"""

from __future__ import annotations

import time
from pathlib import Path

from shapely.geometry import Point

from .clustering import cluster_buildings
from .exporter import write_result
from .grid import ConstraintGrid
from .hydraulics import NewSegment, TechnicalNode, enforce_max_length, size_segment
from .loader import PipelineInputError, load_contest_geojson
from .model import ContestData
from .network import ExistingNetwork
from .postprocess import check_self_intersection, crossings_with, simplify_path
from .reconstruction import compute_reconstruction
from .refdata import RefData
from .tapping import Tap, choose_tap


def run_pipeline(input_path: Path, result_path: Path,
                 refdata: RefData | None = None) -> dict:
    """Полный расчёт по конкурсному набору. Возвращает сводку (metadata)."""
    started = time.time()
    ref = refdata or RefData()

    data: ContestData = load_contest_geojson(input_path)
    net = ExistingNetwork(data.segments, data.chambers)
    warnings: list[str] = list(data.warnings)

    grid = ConstraintGrid(data.bounds, ref)
    grid.apply_constraints(data.constraints)

    max_dirs = int(ref.rule("max_new_directions_per_chamber"))
    clusters = cluster_buildings(data.buildings, ref.rule("cluster_radius_m"))

    new_segments: list[NewSegment] = []
    new_chambers: list[dict] = []
    tech_nodes: list[TechnicalNode] = []
    taps: list[Tap] = []
    unconnected: list[dict] = []
    chamber_load: dict[str, int] = {}
    seq = {"seg": 0, "chamber": 0, "tech": 0}

    for cluster in clusters:
        # В камеру разветвления — не более max_dirs новых направлений:
        # крупные кластеры делим на пачки.
        for pack in _chunk(cluster, max_dirs):
            _process_pack(pack, net, grid, ref, chamber_load, seq,
                          new_segments, new_chambers, tech_nodes, taps,
                          unconnected, warnings)

    recon = compute_reconstruction(net, taps, ref, chamber_load)

    cost_new = sum(s.cost_rub for s in new_segments)
    cost_taps = sum(t.tap_cost_rub for t in taps)
    cost_chambers = sum(c["cost_rub"] for c in new_chambers)
    cost_recon = recon.total_cost_rub
    cost_penalty = len(unconnected) * ref.tariff("unconnected_penalty")
    cost_total = cost_new + cost_taps + cost_chambers + cost_recon + cost_penalty

    summary = {
        "engine": "dit-sprint2",
        "job_elapsed_ms": int((time.time() - started) * 1000),
        "buildings_total": len(data.buildings),
        "buildings_connected": len(data.buildings) - len(unconnected),
        "unconnected_ids": [u["building_id"] for u in unconnected],
        "costs_rub": {
            "new_segments": round(cost_new, 2),
            "tappings": round(cost_taps, 2),
            "new_chambers": round(cost_chambers, 2),
            "reconstruction": round(cost_recon, 2),
            "unconnected_penalty": round(cost_penalty, 2),
            "total": round(cost_total, 2),
        },
        "length_total_m": round(sum(s.length_m for s in new_segments), 1),
        "warnings": warnings,
    }

    write_result(result_path, data, new_segments, new_chambers, tech_nodes,
                 taps, recon, unconnected, summary)
    return summary


def _process_pack(pack, net, grid, ref, chamber_load, seq,
                  new_segments, new_chambers, tech_nodes, taps,
                  unconnected, warnings) -> None:
    """Одна пачка ОКС: общая врезка, ствол, ветви, гидравлика."""
    flow_total = sum(b.flow_tph for b in pack)
    anchors = [b.anchor for b in pack]
    cx = sum(p.x for p in anchors) / len(anchors)
    cy = sum(p.y for p in anchors) / len(anchors)
    cluster_center = Point(cx, cy)

    tap = choose_tap(cluster_center, flow_total, net, ref, chamber_load)
    if tap is None:
        for b in pack:
            unconnected.append({"building_id": b.object_id, "point": b.anchor,
                                "reason": "нет доступных точек врезки в радиусе поиска"})
        return
    taps.append(tap)
    if tap.kind == "existing_chamber":
        chamber_load[tap.chamber_id] = chamber_load.get(tap.chamber_id, 0) + 1
    else:
        seq["chamber"] += 1
        new_chambers.append({
            "object_id": f"new-chamber-{seq['chamber']}",
            "kind": "tapping_on_segment",
            "point": tap.point,
            "segment_id": tap.segment_id,
            "cost_rub": ref.tariff("chamber_new"),
        })

    # Целевые контуры ОКС блокируем, чтобы трасса их не пересекала
    blocked_cells = []
    segs_before = len(new_segments)
    for b in pack:
        if b.geom.geom_type == "Polygon":
            blocked_cells += grid.block_polygon(b.geom)

    try:
        if len(pack) == 1:
            # Раздельное подключение: врезка → точка подключения ОКС
            b = pack[0]
            coords = _route(grid, tap.point, b.anchor, ref)
            if coords is None:
                unconnected.append({"building_id": b.object_id, "point": b.anchor,
                                    "reason": "A* не нашёл маршрут до точки подключения"})
                return
            _append_segment(coords, flow_total, "branch", b.object_id,
                            grid, ref, seq, new_segments, tech_nodes, warnings)
        else:
            # Совместное: ствол до камеры разветвления + ветви
            branch_pt = grid_snap_free(grid, cluster_center)
            trunk = _route(grid, tap.point, branch_pt, ref)
            if trunk is None:
                for b in pack:
                    unconnected.append({"building_id": b.object_id, "point": b.anchor,
                                        "reason": "A* не нашёл маршрут ствола"})
                return
            seq["chamber"] += 1
            new_chambers.append({
                "object_id": f"new-chamber-{seq['chamber']}",
                "kind": "branching",
                "point": branch_pt,
                "segment_id": None,
                "cost_rub": ref.tariff("chamber_new"),
            })
            _append_segment(trunk, flow_total, "trunk",
                            "+".join(b.object_id for b in pack),
                            grid, ref, seq, new_segments, tech_nodes, warnings)
            for b in pack:
                coords = _route(grid, branch_pt, b.anchor, ref)
                if coords is None:
                    unconnected.append({"building_id": b.object_id, "point": b.anchor,
                                        "reason": "A* не нашёл маршрут ветви"})
                    continue
                _append_segment(coords, b.flow_tph, "branch", b.object_id,
                                grid, ref, seq, new_segments, tech_nodes, warnings)
        _assert_tree(new_segments[segs_before:], warnings)
    finally:
        grid.unblock(blocked_cells)


def _append_segment(coords, flow, role, owner_id, grid, ref, seq,
                    new_segments, tech_nodes, warnings) -> None:
    """Постобработка, спецпроходы, диаметр, предельная длина, стоимость."""
    pts = simplify_path(coords, tolerance_m=grid.cell * 0.75)
    if not check_self_intersection(pts):
        warnings.append(f"{owner_id}: самопересечение трассы после упрощения — оставлено как есть")

    bad_crossings = crossings_with(pts, grid_zones(grid))
    if bad_crossings:
        warnings.append(f"{owner_id}: пересечение ограничений {bad_crossings} под углом ниже нормы")

    method = _dominant_method(pts, grid)
    seq["seg"] += 1
    seg = NewSegment(object_id=f"new-seg-{seq['seg']}", coords=pts,
                     flow_tph=flow, role=role, method=method)
    size_segment(seg, ref)
    node_seq = [seq["tech"]]
    parts, nodes = enforce_max_length(seg, ref, node_seq)
    seq["tech"] = node_seq[0]
    tech_nodes.extend(nodes)
    new_segments.extend(parts)


def _route(grid: ConstraintGrid, a: Point, b: Point, ref: RefData):
    return grid.astar((a.x, a.y), (b.x, b.y))


def grid_snap_free(grid: ConstraintGrid, pt: Point) -> Point:
    """Ближайшая свободная ячейка к точке — как Point."""
    cell = grid.nearest_free(grid.to_cell(pt.x, pt.y))
    if cell is None:
        return pt
    x, y = grid.cell_center(*cell)
    return Point(x, y)


def _dominant_method(pts, grid: ConstraintGrid) -> str:
    """Спецпроход, если заметная доля трассы лежит в зоне special_passage.

    Долю считаем по ДЛИНЕ полилинии (интерполяция с шагом пол-ячейки),
    а не по вершинам — после упрощения вершин мало и зону можно проскочить.
    """
    from shapely.geometry import LineString

    line = LineString(pts)
    length = line.length
    if length < 1e-6:
        return "open_trench"
    step = grid.cell / 2.0
    n = max(2, int(length / step) + 1)
    special_m = 0.0
    for k in range(n):
        p = line.interpolate(k * length / (n - 1))
        i, j = grid.to_cell(p.x, p.y)
        if str(grid.zone[i, j]).startswith("special_passage"):
            special_m += step
    min_len = grid.refdata.rule("special_passage_min_len_m")
    if special_m >= min_len:
        return "special_passage"
    return "open_trench"


def grid_zones(grid: ConstraintGrid):
    """Зоны ограничений, сохранённые в сетке (для проверки углов)."""
    return getattr(grid, "_zones", [])


def _chunk(items: list, n: int) -> list[list]:
    return [items[i:i + n] for i in range(0, len(items), n)]


def _assert_tree(segments: list[NewSegment], warnings: list) -> None:
    """Проверка «один путь до ОКС»: компоненты новых сегментов — деревья.

    Для компоненты из E рёбер и V вершин (по округлённым концам)
    должно выполняться E = V - 1, иначе в сети кольцо.
    """
    parent: dict = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    edges = 0
    for seg in segments:
        if len(seg.coords) < 2:
            continue
        a = (round(seg.coords[0][0], 1), round(seg.coords[0][1], 1))
        b = (round(seg.coords[-1][0], 1), round(seg.coords[-1][1], 1))
        edges += 1
        ra, rb = find(a), find(b)
        if ra == rb:
            warnings.append(f"{seg.object_id}: обнаружено кольцо в новой сети")
        else:
            parent[ra] = rb
