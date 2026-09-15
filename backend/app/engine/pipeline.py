"""Оркестрация расчёта: конвейер «файл вошёл — результат вышел».

Спринт 2: обязательные правила §2.3–2.6 ТЗ (граф сети, врезки,
мульти-ОКС, гидравлика, реконструкция, ограничения).
Спринт 3: до трёх СОДЕРЖАТЕЛЬНО РАЗНЫХ вариантов (§2.8):
  V1 — совместное подключение, оптимальные врезки;
  V2 — раздельное подключение каждого ОКС;
  V3 — совместное подключение, альтернативные точки врезки.
Ранжирование: 70% стоимость + 30% протяжённость строительных работ.

Частичный результат (§2.9): ОКС/кластер без точки врезки или маршрута
не роняет расчёт — попадает в перечень unconnected с причиной.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from shapely.geometry import Point

from .clustering import cluster_buildings
from .cost import rank_variants, variant_costs, variant_length_m
from .depth import assign_depth, chamber_depth_m
from .exporter import write_result
from .grid import ConstraintGrid
from .hydraulics import NewSegment, TechnicalNode, enforce_max_length, size_segment
from .loader import load_contest_geojson
from .model import ContestData
from .network import ExistingNetwork
from .postprocess import check_self_intersection, simplify_path
from .reconstruction import compute_reconstruction
from .refdata import RefData
from .tapping import Tap, choose_tap_ranked


@dataclass(frozen=True)
class Strategy:
    """Стратегия построения варианта (§2.8)."""

    label: str
    cluster: bool       # совместное подключение кластеров ОКС
    tap_rank: int       # 0 — лучшая врезка, 1 — вторая и т.д.


STRATEGIES = [
    Strategy("Совместное подключение, оптимальные врезки", cluster=True, tap_rank=0),
    Strategy("Раздельное подключение", cluster=False, tap_rank=0),
    Strategy("Совместное подключение, альтернативные врезки", cluster=True, tap_rank=1),
]


def run_pipeline(input_path: Path, result_path: Path,
                 refdata: RefData | None = None) -> dict:
    """Полный расчёт по конкурсному набору: до 3 вариантов + ранжирование."""
    started = time.time()
    ref = refdata or RefData()

    data: ContestData = load_contest_geojson(input_path)
    net = ExistingNetwork(data.segments, data.chambers)

    # Сетка ограничений общая для всех вариантов (временные блокировки
    # контуров ОКС снимаются в finally — состояние между вариантами чистое).
    grid = ConstraintGrid(data.bounds, ref)
    grid.apply_constraints(data.constraints)

    variants: list[dict] = []
    seen_signatures: set[tuple] = set()
    for strategy in STRATEGIES:
        variant = _compute_variant(data, net, grid, ref, strategy)
        signature = _variant_signature(variant)
        if variants and signature in seen_signatures:
            continue  # содержательно не отличается — не плодим дубликаты
        seen_signatures.add(signature)
        variants.append(variant)
        if len(variants) >= 3:
            break

    rank_variants(variants)

    best = variants[0] if variants else _empty_variant()
    summary = {
        "engine": "dit-sprint4.1",  # + дельта техприложения 5/2/1
        "job_elapsed_ms": int((time.time() - started) * 1000),
        "buildings_total": len(data.buildings),
        "buildings_connected": len(data.buildings) - len(best["unconnected_ids"]),
        "unconnected_ids": best["unconnected_ids"],
        "costs_rub": best["costs"],
        "length_total_m": best["length_total_m"],
        "warnings": data.warnings + best["warnings"],
        "variants": [_variant_public(v) for v in variants],
    }

    write_result(result_path, data, variants, summary)
    return summary


# ---------------------------------------------------------------------------
# Один вариант
# ---------------------------------------------------------------------------

def _compute_variant(data: ContestData, net: ExistingNetwork,
                     grid: ConstraintGrid, ref: RefData,
                     strategy: Strategy) -> dict:
    max_dirs = int(ref.rule("max_new_directions_per_chamber"))

    if strategy.cluster:
        groups = cluster_buildings(data.buildings, ref.rule("cluster_radius_m"))
    else:
        groups = [[b] for b in data.buildings.values()]

    new_segments: list[NewSegment] = []
    new_chambers: list[dict] = []
    tech_nodes: list[TechnicalNode] = []
    taps: list[Tap] = []
    unconnected: list[dict] = []
    chamber_load: dict[str, int] = {}
    warnings: list[str] = []
    seq = {"seg": 0, "chamber": 0, "tech": 0}

    for group in groups:
        for pack in _chunk(group, max_dirs):
            _process_pack(pack, net, grid, ref, strategy, chamber_load, seq,
                          new_segments, new_chambers, tech_nodes, taps,
                          unconnected, warnings)

    recon = compute_reconstruction(net, taps, ref, chamber_load)
    costs = variant_costs(new_segments, new_chambers, taps, recon, unconnected, ref)

    return {
        "label": strategy.label,
        "new_segments": new_segments,
        "new_chambers": new_chambers,
        "tech_nodes": tech_nodes,
        "taps": taps,
        "recon": recon,
        "unconnected": unconnected,
        "unconnected_ids": [u["building_id"] for u in unconnected],
        "warnings": warnings,
        "costs": costs,
        "length_total_m": variant_length_m(new_segments),
    }


def _empty_variant() -> dict:
    return {"unconnected_ids": [], "warnings": [],
            "costs": {"total": 0.0}, "length_total_m": 0.0}


def _variant_signature(variant: dict) -> tuple:
    """Сигнатура для отсева дубликатов: набор врезок + набор трасс."""
    taps_sig = tuple(sorted(
        (t.kind, round(t.point.x), round(t.point.y)) for t in variant["taps"]))
    segs_sig = tuple(sorted(
        (s.role, round(s.length_m), s.diameter_mm) for s in variant["new_segments"]))
    return taps_sig + segs_sig


def _variant_public(v: dict) -> dict:
    """Публичная сводка варианта для metadata (без внутренних объектов)."""
    return {
        "rank": v.get("rank"),
        "label": v["label"],
        "score": v.get("score"),
        "is_recommended": v.get("is_recommended", False),
        "status": "partial" if v["unconnected_ids"] else "done",
        "costs_rub": v["costs"],
        "length_total_m": v["length_total_m"],
        "unconnected_ids": v["unconnected_ids"],
        "counts": {
            "new_segments": len(v["new_segments"]),
            "new_chambers": len(v["new_chambers"]),
            "technical_nodes": len(v["tech_nodes"]),
            "reconstruction_segments": len(v["recon"].segments),
            "reconstruction_chambers": len(v["recon"].chambers),
        },
    }


# ---------------------------------------------------------------------------
# Пачка ОКС внутри варианта
# ---------------------------------------------------------------------------

def _process_pack(pack, net, grid, ref, strategy, chamber_load, seq,
                  new_segments, new_chambers, tech_nodes, taps,
                  unconnected, warnings) -> None:
    """Одна пачка ОКС: врезка, (ствол), ветви, гидравлика."""
    # §2.9: ОКС с точкой подключения в запретной зоне — сразу в unconnected
    reachable = []
    for b in pack:
        zone_id = grid.forbidden_reason(b.anchor)
        if zone_id:
            unconnected.append({
                "building_id": b.object_id, "point": b.anchor,
                "reason": f"точка подключения в запретной зоне {zone_id}"})
        else:
            reachable.append(b)
    pack = reachable
    if not pack:
        return
    flow_total = sum(b.flow_tph for b in pack)
    anchors = [b.anchor for b in pack]
    cx = sum(p.x for p in anchors) / len(anchors)
    cy = sum(p.y for p in anchors) / len(anchors)
    cluster_center = Point(cx, cy)

    candidates = choose_tap_ranked(cluster_center, flow_total, net, ref, chamber_load)
    if not candidates:
        for b in pack:
            unconnected.append({"building_id": b.object_id, "point": b.anchor,
                                "reason": "нет доступных точек врезки в радиусе поиска"})
        return
    tap = candidates[min(strategy.tap_rank, len(candidates) - 1)]
    taps.append(tap)
    if tap.kind == "existing_chamber":
        chamber_load[tap.chamber_id] = chamber_load.get(tap.chamber_id, 0) + 1
    else:
        seq["chamber"] += 1
        tap_dn = ref.diameter_for_flow(flow_total)["dn_mm"]
        new_chambers.append({
            "object_id": f"new-chamber-{seq['chamber']}",
            "kind": "tapping_on_segment",
            "point": tap.point,
            "segment_id": tap.segment_id,
            "cost_rub": ref.tariff("chamber_new"),
            "depth_m": chamber_depth_m(ref, tap_dn),
        })

    # Целевые контуры ОКС блокируем, чтобы трасса их не пересекала
    blocked_cells = []
    segs_before = len(new_segments)
    for b in pack:
        if b.geom.geom_type == "Polygon":
            blocked_cells += grid.block_polygon(b.geom)

    try:
        if len(pack) == 1:
            b = pack[0]
            coords = _route(grid, tap.point, b.anchor)
            if coords is None:
                unconnected.append({"building_id": b.object_id, "point": b.anchor,
                                    "reason": "A* не нашёл маршрут до точки подключения"})
                return
            _append_segment(coords, flow_total, "branch", b.object_id,
                            grid, ref, seq, new_segments, tech_nodes, warnings)
        else:
            branch_pt = grid_snap_free(grid, cluster_center)
            trunk = _route(grid, tap.point, branch_pt)
            if trunk is None:
                for b in pack:
                    unconnected.append({"building_id": b.object_id, "point": b.anchor,
                                        "reason": "A* не нашёл маршрут ствола"})
                return
            seq["chamber"] += 1
            trunk_dn = ref.diameter_for_flow(flow_total)["dn_mm"]
            new_chambers.append({
                "object_id": f"new-chamber-{seq['chamber']}",
                "kind": "branching",
                "point": branch_pt,
                "segment_id": None,
                "cost_rub": ref.tariff("chamber_new"),
                "depth_m": chamber_depth_m(ref, trunk_dn),
            })
            trunk_depth = _append_segment(
                trunk, flow_total, "trunk",
                "+".join(b.object_id for b in pack),
                grid, ref, seq, new_segments, tech_nodes, warnings)
            for b in pack:
                coords = _route(grid, branch_pt, b.anchor)
                if coords is None:
                    unconnected.append({"building_id": b.object_id, "point": b.anchor,
                                        "reason": "A* не нашёл маршрут ветви"})
                    continue
                _append_segment(coords, b.flow_tph, "branch", b.object_id,
                                grid, ref, seq, new_segments, tech_nodes, warnings,
                                entry_depth_m=trunk_depth)
        _assert_tree(new_segments[segs_before:], warnings)
    finally:
        grid.unblock(blocked_cells)


def _append_segment(coords, flow, role, owner_id, grid, ref, seq,
                    new_segments, tech_nodes, warnings,
                    entry_depth_m=None) -> float:
    """Постобработка, спецпроходы, диаметр, предельная длина, глубина.

    Возвращает глубину заложения в начале участка — как входную отметку
    для примыкающих ветвей (задание на глубину, Спринт 4).
    """
    pts = simplify_path(coords, tolerance_m=grid.cell * 0.75)
    if not check_self_intersection(pts):
        warnings.append(f"{owner_id}: самопересечение трассы после упрощения — оставлено как есть")

    method, k_special = _dominant_passage(pts, grid)
    seq["seg"] += 1
    seg = NewSegment(object_id=f"new-seg-{seq['seg']}", coords=pts,
                     flow_tph=flow, role=role, method=method, k_special=k_special)
    size_segment(seg, ref)
    node_seq = [seq["tech"]]
    parts, nodes = enforce_max_length(seg, ref, node_seq)
    seq["tech"] = node_seq[0]
    tech_nodes.extend(nodes)
    depth_in = entry_depth_m
    for part in parts:
        assign_depth(part, ref, entry_depth_m=depth_in)
        # непрерывность профиля: конец подучастка — вход для следующего
        if part.coords3d:
            depth_in = -part.coords3d[-1][2]
    new_segments.extend(parts)
    return parts[0].depth_m if parts else 0.0


def _route(grid: ConstraintGrid, a: Point, b: Point):
    return grid.astar((a.x, a.y), (b.x, b.y))


def grid_snap_free(grid: ConstraintGrid, pt: Point) -> Point:
    """Ближайшая свободная ячейка к точке — как Point."""
    cell = grid.nearest_free(grid.to_cell(pt.x, pt.y))
    if cell is None:
        return pt
    x, y = grid.cell_center(*cell)
    return Point(x, y)


def _dominant_passage(pts, grid: ConstraintGrid) -> tuple[str, float | None]:
    """Метод прокладки и Kспец доминирующей зоны special_passage.

    Долю считаем по ДЛИНЕ полилинии (интерполяция с шагом пол-ячейки),
    а не по вершинам — после упрощения вершин мало и зону можно проскочить.
    Возвращает (method, Kспец): Kспец берётся из параметров зоны
    (grid.zone_k), None — если спецпрохода нет.
    """
    from shapely.geometry import LineString

    line = LineString(pts)
    length = line.length
    if length < 1e-6:
        return "open_trench", None
    step = grid.cell / 2.0
    n = max(2, int(length / step) + 1)
    special_m: dict[str, float] = {}
    for k in range(n):
        p = line.interpolate(k * length / (n - 1))
        i, j = grid.to_cell(p.x, p.y)
        tag = str(grid.zone[i, j])
        if tag.startswith("special_passage:"):
            zone_id = tag.split(":", 1)[1]
            special_m[zone_id] = special_m.get(zone_id, 0.0) + step
    min_len = grid.refdata.rule("special_passage_min_len_m")
    if not special_m:
        return "open_trench", None
    zone_id, best_m = max(special_m.items(), key=lambda kv: kv[1])
    if best_m < min_len:
        return "open_trench", None
    k_special = grid.zone_k.get(zone_id, grid.default_special_mult)
    return "special_passage", k_special


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

    for seg in segments:
        if len(seg.coords) < 2:
            continue
        a = (round(seg.coords[0][0], 1), round(seg.coords[0][1], 1))
        b = (round(seg.coords[-1][0], 1), round(seg.coords[-1][1], 1))
        ra, rb = find(a), find(b)
        if ra == rb:
            warnings.append(f"{seg.object_id}: обнаружено кольцо в новой сети")
        else:
            parent[ra] = rb
