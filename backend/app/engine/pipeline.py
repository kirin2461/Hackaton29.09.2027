"""Оркестрация расчёта: конвейер «файл вошёл — результат вышел».

Соответствие техприложению ЛЦТ-2026:
  §2.1–2.2 — официальная входная схема (loader);
  §3       — предельные длины непрерывных цепочек одного Ду (hydraulics);
  §4       — диаметры/ставки по таблице 4.1 (refdata);
  §5.1     — ограничения: отступы 5/7/9 м по Ду, спецпроходы с Kспец,
             границы спецучастков, угол пересечения ≥45° (grid/postprocess);
  §6       — задание на глубину, режим ENGINE_DEPTH_MODE=1 (depth);
  §7       — реконструкция существующей сети, частичная геометрия (reconstruction);
  §8.2     — врезки (5 млн ₽) и камеры по шкале (tapping/cost);
  §8.3     — штраф 100 млн + 500 тыс.×G за неподключённый ОКС (cost);
  §9       — ранжирование S = 0,3·C/25 млн + 0,7·L/100 (протяжённость важнее;
  §10      — выходной GeoJSON, строгий контракт (exporter).

Вариантность (до трёх СОДЕРЖАТЕЛЬНО разных вариантов): топология
подключения (ствол/раздельно) и коридоры маршрутизации; точка врезки
детерминирована §8.2 и вариантности не даёт.

Частичный результат (§2.9): ОКС/кластер без точки врезки или маршрута
не роняет расчёт — попадает в unconnected со штрафом §8.3.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path

from shapely.geometry import LineString, Point

from .clustering import cluster_buildings
from .cost import rank_variants, variant_costs, variant_lengths_m
from .depth import apply_depth
from .exporter import write_result
from .grid import ConstraintGrid
from .hydraulics import NewSegment, TechnicalNode, enforce_max_length_chains, size_segment, subline
from .loader import load_contest_geojson
from .model import ContestData
from .network import ExistingNetwork
from .postprocess import check_crossing_angles, check_self_intersection, simplify_path
from .reconstruction import compute_reconstruction
from .refdata import RefData
from .tapping import Tap, choose_tap_strict

ENGINE_VERSION = "dit-sprint5.0"


@dataclass(frozen=True)
class Strategy:
    """Стратегия построения варианта."""

    label: str
    cluster: bool                 # совместное подключение кластеров ОКС
    turn_penalty_mult: float = 1.0  # множитель штрафа за поворот (коридор A*)
    avoid_previous: bool = False    # обходить коридоры трасс предыдущих вариантов


STRATEGIES = [
    Strategy("Совместное подключение, базовый коридор", cluster=True),
    Strategy("Раздельное подключение", cluster=False),
    Strategy("Совместное подключение, альтернативный коридор",
             cluster=True, turn_penalty_mult=4.0, avoid_previous=True),
]


def run_pipeline(input_path: Path, result_path: Path,
                 refdata: RefData | None = None) -> dict:
    """Полный расчёт по конкурсному набору: до 3 вариантов + ранжирование §9."""
    started = time.time()
    ref = refdata or RefData()

    data: ContestData = load_contest_geojson(input_path, refdata=ref)
    net = ExistingNetwork(data.segments, data.chambers, data.sources)

    # Сетка ограничений общая для всех вариантов (временные блокировки
    # контуров ОКС и отступов под Ду снимаются — состояние между
    # вариантами чистое).
    grid = ConstraintGrid(data.bounds, ref)
    grid.apply_constraints(data.constraints)

    variants: list[dict] = []
    seen_signatures: set[tuple] = set()
    prev_paths: list = []
    for strategy in STRATEGIES:
        changed = []
        if strategy.avoid_previous and prev_paths:
            changed = grid.penalize_corridor(
                prev_paths,
                radius_m=float(ref.rule("corridor_avoid_radius_m")),
                factor=float(ref.rule("corridor_avoid_factor")))
        try:
            variant = _compute_variant(data, net, grid, ref, strategy)
        finally:
            grid.restore_mult(changed)
        signature = _variant_signature(variant)
        if variants and signature in seen_signatures:
            continue  # содержательно не отличается — не плодим дубликаты
        seen_signatures.add(signature)
        variants.append(variant)
        prev_paths.extend(s.coords for s in variant["new_segments"])
        if len(variants) >= 3:
            break

    rank_variants(variants, ref)

    best = variants[0] if variants else _empty_variant()
    summary = {
        "engine": ENGINE_VERSION,
        "job_elapsed_ms": int((time.time() - started) * 1000),
        "buildings_total": len(data.buildings),
        "buildings_connected": len(data.buildings) - len(best["unconnected_ids"]),
        "unconnected_ids": best["unconnected_ids"],
        "costs_rub": {**best["costs"], "total": best["costs"]["calculated_cost"]},
        "length_total_m": best["lengths"]["length"],
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
    depth_mode = os.getenv("ENGINE_DEPTH_MODE") == "1"

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
    seq = {"seg": 0, "chamber": 0, "tech": 0, "tie": 0}

    for group in groups:
        for pack in _chunk(group, max_dirs):
            _process_pack(pack, net, grid, ref, strategy, chamber_load, seq,
                          new_segments, new_chambers, tech_nodes, taps,
                          unconnected, warnings)

    # §3: предельные длины непрерывных цепочек одного Ду (без сброса
    # на камерах/техузлах) — повышение диаметра при превышении
    enforce_max_length_chains(new_segments, ref, warnings)

    # Раздел 7 + §8.2: реконструкция сети и камер
    recon = compute_reconstruction(net, taps, ref, warnings)

    # §8.2/§10.4: диаметр и стоимость новых камер — по итоговым примыканиям
    _finalize_chambers(new_chambers, new_segments, taps, recon, net, ref)

    # Раздел 6 (доп. задача): вертикальный профиль — только в режиме глубины
    if depth_mode:
        deep: list[NewSegment] = []
        for seg in new_segments:
            deep.extend(apply_depth(seg, ref, seq, tech_nodes, grid.special_zones))
        new_segments = deep

    costs = variant_costs(new_segments, new_chambers, taps, recon, unconnected, ref)
    lengths = variant_lengths_m(new_segments, recon)

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
        "lengths": lengths,
    }


def _empty_variant() -> dict:
    return {"unconnected_ids": [], "warnings": [],
            "costs": {"calculated_cost": 0.0},
            "lengths": {"length": 0.0, "new_network_length": 0.0,
                        "reconstruction_length": 0.0}}


def _variant_signature(variant: dict) -> tuple:
    """Сигнатура для отсева дубликатов: набор врезок + набор трасс."""
    taps_sig = tuple(sorted(
        (t.kind, round(t.point.x), round(t.point.y)) for t in variant["taps"]))
    segs_sig = tuple(sorted(
        (s.role, round(s.length_m), s.diameter_mm) for s in variant["new_segments"]))
    return taps_sig + segs_sig


def _variant_public(v: dict) -> dict:
    """Публичная сводка варианта (для служебного summary движка)."""
    return {
        "rank": v.get("rank"),
        "label": v["label"],
        "score": v.get("score"),
        "is_recommended": v.get("is_recommended", False),
        "status": "partial" if v["unconnected_ids"] else "done",
        "costs_rub": {**v["costs"], "total": v["costs"]["calculated_cost"]},
        "length_total_m": v["lengths"]["length"],
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
    """Одна пачка ОКС: врезка (§8.2), (ствол), ветви, гидравлика."""
    # §2.9: ОКС с точкой подключения в запретной зоне — сразу в unconnected
    reachable = []
    for b in pack:
        dn_b = ref.diameter_for_flow(b.flow_tph)["dn_mm"]
        zone_id = grid.forbidden_reason(b.anchor, dn_mm=dn_b)
        if zone_id:
            unconnected.append({
                "building_id": b.object_id, "point": b.anchor,
                "flow_tph": b.flow_tph,
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

    tap = choose_tap_strict(cluster_center, flow_total, net, ref, chamber_load)
    if tap is None:
        for b in pack:
            unconnected.append({"building_id": b.object_id, "point": b.anchor,
                                "flow_tph": b.flow_tph,
                                "reason": "нет доступных точек врезки в радиусе поиска"})
        return
    seq["tie"] += 1
    tap.node_id = f"tie-{seq['tie']}"
    taps.append(tap)

    if tap.kind == "existing_chamber":
        chamber_load[tap.chamber_id] = chamber_load.get(tap.chamber_id, 0) + 1
        tap_node = tap.chamber_id
    else:
        seq["chamber"] += 1
        tap_node = f"ch-{seq['chamber']}"
        new_chambers.append({
            "object_id": tap_node,
            "kind": "tapping_on_segment",
            "point": tap.point,
            "segment_id": tap.segment_id,
            "tap_required_dn": tap.required_dn,
            "diameter_mm": 0.0,   # пост-проход _finalize_chambers
            "cost_rub": 0.0,
        })

    # Целевые контуры ОКС блокируем, чтобы трасса их не пересекала
    blocked_cells = []
    segs_before = len(new_segments)
    for b in pack:
        if b.geom.geom_type in ("Polygon", "MultiPolygon"):
            blocked_cells += grid.block_polygon(b.geom)

    try:
        turn_penalty = ref.rule("turn_penalty_m") * strategy.turn_penalty_mult
        pack_dn = ref.diameter_for_flow(flow_total)["dn_mm"]
        if len(pack) == 1:
            b = pack[0]
            coords = _route(grid, tap.point, b.anchor, turn_penalty, pack_dn)
            if coords is None:
                unconnected.append({"building_id": b.object_id, "point": b.anchor,
                                    "flow_tph": b.flow_tph,
                                    "reason": "A* не нашёл маршрут до точки подключения"})
                return
            _append_segment(coords, flow_total, "branch", tap_node,
                            _end_node(b), grid, ref, seq,
                            new_segments, tech_nodes, warnings, b.object_id)
        else:
            branch_pt = grid_snap_free(grid, cluster_center)
            trunk = _route(grid, tap.point, branch_pt, turn_penalty, pack_dn)
            if trunk is None:
                for b in pack:
                    unconnected.append({"building_id": b.object_id, "point": b.anchor,
                                        "flow_tph": b.flow_tph,
                                        "reason": "A* не нашёл маршрут ствола"})
                return
            seq["chamber"] += 1
            branch_node = f"ch-{seq['chamber']}"
            new_chambers.append({
                "object_id": branch_node,
                "kind": "branching",
                "point": branch_pt,
                "segment_id": None,
                "tap_required_dn": 0.0,
                "diameter_mm": 0.0,
                "cost_rub": 0.0,
            })
            _append_segment(trunk, flow_total, "trunk", tap_node, branch_node,
                            grid, ref, seq, new_segments, tech_nodes, warnings,
                            "+".join(b.object_id for b in pack))
            for b in pack:
                dn_b = ref.diameter_for_flow(b.flow_tph)["dn_mm"]
                coords = _route(grid, branch_pt, b.anchor, turn_penalty, dn_b)
                if coords is None:
                    unconnected.append({"building_id": b.object_id, "point": b.anchor,
                                        "flow_tph": b.flow_tph,
                                        "reason": "A* не нашёл маршрут ветви"})
                    continue
                _append_segment(coords, b.flow_tph, "branch", branch_node,
                                _end_node(b), grid, ref, seq,
                                new_segments, tech_nodes, warnings, b.object_id)
        _assert_tree(new_segments[segs_before:], warnings)
    finally:
        grid.unblock(blocked_cells)


def _end_node(b) -> str:
    """Конечный узел ветви: точка подключения ОКС (§10.1)."""
    return b.connection_point_id or f"oks-{b.object_id}"


def _append_segment(coords, flow, role, start_node_id, end_node_id,
                    grid, ref, seq, new_segments, tech_nodes, warnings,
                    owner_id) -> None:
    """Постобработка, границы спецучастков (таблица 5.1), диаметр, узлы."""
    pts = simplify_path(coords, tolerance_m=grid.cell * 0.75)
    if not check_self_intersection(pts):
        warnings.append(f"{owner_id}: самопересечение трассы после упрощения — оставлено как есть")

    line = LineString(pts)
    length = line.length
    min_special = float(ref.rule("special_passage_min_len_m"))
    intervals = [(a, b, zid, k) for a, b, zid, k in grid.special_intervals(line)
                 if b - a >= min_special]

    # точки деления: границы спецучастков
    cuts = sorted({0.0, length} | {x for a, b, _, _ in intervals for x in (a, b)})

    def _method(a: float, b: float) -> tuple[str, float | None]:
        mid = (a + b) / 2.0
        for ia, ib, _zid, k in intervals:
            if ia <= mid <= ib:
                return "special", k
        return "base", None

    parts = [(a, b) for a, b in zip(cuts, cuts[1:]) if b - a > 0.01]
    cur_start = start_node_id
    for idx, (a, b) in enumerate(parts):
        method, k_special = _method(a, b)
        piece = subline(line, a, b)
        is_last = idx == len(parts) - 1
        if is_last:
            end_node = end_node_id
        else:
            seq["tech"] += 1
            end_node = f"node-{seq['tech']}"
            tech_nodes.append(TechnicalNode(
                object_id=end_node,
                point=line.interpolate(b),
                reason="граница специального участка (таблица 5.1)"))
        seq["seg"] += 1
        seg = NewSegment(
            object_id=f"seg-{seq['seg']}",
            coords=[(c[0], c[1]) for c in piece.coords],
            flow_tph=flow,
            role=role,
            method=method,
            k_special=k_special,
            start_node_id=cur_start,
            end_node_id=end_node,
        )
        size_segment(seg, ref)
        new_segments.append(seg)
        cur_start = end_node

    check_crossing_angles(line, grid.special_zones, warnings, owner_id)


def _route(grid: ConstraintGrid, a: Point, b: Point,
           turn_penalty_m: float | None, dn_mm: float):
    """A* с временными отступами запретных зон под диаметр трассы (§5.1)."""
    blocked = grid.clearance_block(dn_mm)
    try:
        return grid.astar((a.x, a.y), (b.x, b.y), turn_penalty_m=turn_penalty_m)
    finally:
        grid.clearance_unblock(blocked)


def grid_snap_free(grid: ConstraintGrid, pt: Point) -> Point:
    """Ближайшая свободная ячейка к точке — как Point."""
    cell = grid.nearest_free(grid.to_cell(pt.x, pt.y))
    if cell is None:
        return pt
    x, y = grid.cell_center(*cell)
    return Point(x, y)


def _finalize_chambers(new_chambers, new_segments, taps, recon, net, ref) -> None:
    """§8.2/§10.4: диаметр новой камеры — максимум Ду примыкающих участков
    в итоговом варианте; стоимость — по шкале §8.2."""
    # требуемый Ду существующих участков после реконструкции
    recon_required: dict[str, float] = {}
    for rs in recon.segments:
        recon_required[rs.existing_object_id] = max(
            recon_required.get(rs.existing_object_id, 0.0), rs.required_dn)

    for ch in new_chambers:
        cid = ch["object_id"]
        dns = [s.diameter_mm for s in new_segments
               if s.start_node_id == cid or s.end_node_id == cid]
        if ch.get("tap_required_dn"):
            dns.append(ch["tap_required_dn"])
        if ch.get("segment_id"):
            sid = ch["segment_id"]
            seg0 = net.segments.get(sid)
            if seg0 is not None:
                dns.append(recon_required.get(sid, seg0.diameter_mm or 0.0))
        max_dn = max(dns) if dns else ref.diameters[0]["dn_mm"]
        ch["diameter_mm"] = max_dn
        ch["cost_rub"] = ref.chamber_cost(max_dn)


def _chunk(items: list, n: int) -> list[list]:
    return [items[i:i + n] for i in range(0, len(items), n)]


def _assert_tree(segments: list[NewSegment], warnings: list) -> None:
    """Проверка «один путь до ОКС»: компоненты новых сегментов — деревья.

    Для компоненты из E рёбер и V вершин (по id узлов) должно
    выполняться E = V - 1, иначе в сети кольцо.
    """
    parent: dict = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for seg in segments:
        if not seg.start_node_id or not seg.end_node_id:
            continue
        ra, rb = find(seg.start_node_id), find(seg.end_node_id)
        if ra == rb:
            warnings.append(f"{seg.object_id}: обнаружено кольцо в новой сети")
        else:
            parent[ra] = rb
