"""Задание на глубину (раздел 6, доп. задача): вертикальный профиль трассы.

Режим включается ENGINE_DEPTH_MODE=1. В основной двумерной задаче (§8.1)
глубины не вычисляются — depth_start/depth_end = null, Kгл = 1.

Правила раздела 6:
  - базовая глубина до верха расчётного габарита — 3,0 м, минимум 0,7 м;
  - отметки дискретизируются шагом 0,5 м;
  - продольный уклон смены глубины ≤ 0,10 м/м (пандусы между отметками);
  - на точечных пересечениях — горизонтальная площадка 4,0 м;
  - газ/кабель/теплосеть: проход ВЫШЕ или НИЖЕ — выбирается более дешёвый
    (с учётом Kгл), с минимальным вертикальным просветом из таблицы 5.1;
  - Kгл = 1 + 0,10·(h − 3) при h > 3 м (при h ≤ 3 м Kгл = 1);
  - в точках пересечения профилем отметки 3,0 м ставится технический узел,
    участок делится на части.
"""

from __future__ import annotations

import math

from shapely.geometry import LineString, Point

from .hydraulics import NewSegment, TechnicalNode, subline
from .refdata import RefData


def quantize(depth_m: float, ref: RefData) -> float:
    """Квантование отметки шагом 0,5 м с соблюдением минимума 0,7 м."""
    step = ref.depth_rule("step_m", 0.5)
    dmin = ref.depth_rule("min_depth_m", 0.7)
    return max(dmin, round(round(depth_m / step) * step, 3))


def target_depth_m(ref: RefData) -> float:
    """Целевая (базовая) глубина заложения, квантованная шагом."""
    return quantize(ref.depth_rule("base_depth_m", 3.0), ref)


def chamber_depth_m(ref: RefData, connecting_dn_mm: float | None = None) -> float:
    """Отметка дна камеры: базовая глубина + высота габарита + запас."""
    h = ref.envelope_height_m(connecting_dn_mm) if connecting_dn_mm else 0.0
    return quantize(ref.depth_rule("base_depth_m", 3.0) + h + 0.25, ref)


def _crossing_constraints(seg: NewSegment, ref: RefData,
                          special_zones: list) -> list[tuple[float, float, float]]:
    """Требуемые отметки на пересечениях: [(start_m, end_m, depth_m)].

    Для газопровода/кабеля/теплосети — выбор «выше или ниже» по цене
    (дешевле тот вариант, у которого Kгл меньше). Для дороги/трамвая
    (под объектом) базовая глубина 3,0 м уже удовлетворяет просвету —
    ограничение добавляется только если просвет не выполняется.
    """
    line = LineString(seg.coords)
    length = line.length
    base = target_depth_m(ref)
    flat = ref.depth_rule("crossing_flat_m", 4.0)
    out: list[tuple[float, float, float]] = []
    env_h = ref.envelope_height_m(seg.diameter_mm)

    for z in special_zones:
        if not line.intersects(z.geom):
            continue
        rule = ref.restriction_rule(z.restriction_type) or {}
        vert = rule.get("vertical_clearance_m")
        under = rule.get("under_clearance_m")
        if vert is None and under is None:
            continue
        inter = line.intersection(z.geom)
        ds = [line.project(Point(p)) for p in _points_of(inter)]
        if not ds:
            continue
        d = (min(ds) + max(ds)) / 2.0
        if under is not None:
            need = quantize(float(under) + 0.0, ref)  # верх габарита глубже просвета
            if need > base:
                out.append((max(0.0, d - flat / 2), min(length, d + flat / 2), need))
            continue
        # выше или ниже существующей коммуникации — что дешевле
        exist_d = float(ref.depth.get("existing_depth_m", {}).get(
            z.restriction_type or "", 1.5))
        above = quantize(exist_d - float(vert) - env_h, ref)
        below = quantize(exist_d + float(vert) + env_h, ref)
        chosen = above if ref.depth_k(above) <= ref.depth_k(below) else below
        if abs(chosen - base) > 1e-9:
            out.append((max(0.0, d - flat / 2), min(length, d + flat / 2), chosen))
    return out


def _points_of(geom) -> list[tuple[float, float]]:
    t = geom.geom_type
    if t == "Point":
        return [(geom.x, geom.y)]
    if t == "MultiPoint":
        return [(p.x, p.y) for p in geom.geoms]
    if t == "LineString":
        return list(geom.coords)
    if t in ("MultiLineString", "GeometryCollection"):
        pts: list[tuple[float, float]] = []
        for g in geom.geoms:
            pts.extend(_points_of(g))
        return pts
    return [(geom.representative_point().x, geom.representative_point().y)]


def _profile(length: float, constraints: list[tuple[float, float, float]],
             entry_depth_m: float | None, ref: RefData) -> list[tuple[float, float]]:
    """Продольный профиль: [(distance_m, depth_m)] с пандусами ≤ max_slope.

    Требуемые отметки соединяются с базовой глубиной пандусами
    ограниченного уклона; результат квантуется шагом 0,5 м.
    """
    base = target_depth_m(ref)
    slope = max(ref.depth_rule("max_slope", 0.10), 1e-6)
    step = 2.0
    n = max(2, int(length / step) + 1)
    xs = [i * length / (n - 1) for i in range(n)]
    # целевая отметка: база, жёсткие ограничения пересечений, входная отметка
    target = [base] * n
    if entry_depth_m is not None:
        target[0] = quantize(entry_depth_m, ref)
    for a, b, h in constraints:
        for i, x in enumerate(xs):
            if a - 1e-9 <= x <= b + 1e-9:
                if h > base:
                    target[i] = max(target[i], h)
                else:
                    target[i] = h if target[i] == base else min(target[i], h)

    # сглаживание уклоном: прямой и обратный проход
    prof = list(target)
    for _ in range(4):
        for i in range(1, n):
            prof[i] = min(prof[i], prof[i - 1] + slope * (xs[i] - xs[i - 1])) \
                if prof[i] > prof[i - 1] else max(prof[i], prof[i - 1] - slope * (xs[i] - xs[i - 1]))
        for i in range(n - 2, -1, -1):
            prof[i] = min(prof[i], prof[i + 1] + slope * (xs[i + 1] - xs[i])) \
                if prof[i] > prof[i + 1] else max(prof[i], prof[i + 1] - slope * (xs[i + 1] - xs[i]))
        # ограничения — жёсткие: восстанавливаем после сглаживания
        for a, b, h in constraints:
            for i, x in enumerate(xs):
                if a - 1e-9 <= x <= b + 1e-9:
                    if h > base:
                        prof[i] = max(prof[i], h)
                    else:
                        prof[i] = min(prof[i], h)
    return [(x, quantize(h, ref)) for x, h in zip(xs, prof)]


def apply_depth(seg: NewSegment, ref: RefData, seq: dict,
                tech_nodes: list[TechnicalNode], special_zones: list,
                entry_depth_m: float | None = None) -> list[NewSegment]:
    """Построить профиль §6, разрезать участок на отметке 3,0 м, посчитать Kгл.

    Возвращает список подучастков с depth_start/depth_end и coords3d;
    в точках пересечения профилем отметки free_depth ставятся техузлы.
    """
    line = LineString(seg.coords)
    length = line.length
    base = target_depth_m(ref)
    constraints = _crossing_constraints(seg, ref, special_zones)
    prof = _profile(length, constraints, entry_depth_m, ref)

    # точки деления: где профиль пересекает базовую отметку (смена режима)
    cuts = [0.0]
    for i in range(1, len(prof)):
        h0, h1 = prof[i - 1][1], prof[i][1]
        if (h0 - base) * (h1 - base) < 0:
            x0, x1 = prof[i - 1][0], prof[i][0]
            t = (base - h0) / (h1 - h0)
            cuts.append(x0 + t * (x1 - x0))
    cuts.append(length)
    cuts = sorted(set(round(c, 2) for c in cuts))

    parts: list[NewSegment] = []
    cur_start_node = seg.start_node_id
    for k in range(len(cuts) - 1):
        a, b = cuts[k], cuts[k + 1]
        if b - a < 0.01:
            continue
        piece = subline(line, a, b)
        # глубины на концах куска — интерполяция профиля
        d_a = _depth_at(prof, a)
        d_b = _depth_at(prof, b)
        is_last = k == len(cuts) - 2
        if is_last:
            end_node = seg.end_node_id
        else:
            seq["tech"] += 1
            end_node = f"node-{seq['tech']}"
            tech_nodes.append(TechnicalNode(
                object_id=end_node,
                point=line.interpolate(b),
                reason="пересечение отметки 3,0 м (раздел 6)"))
        part = NewSegment(
            object_id=seg.object_id if k == 0 and is_last else f"{seg.object_id}.{k + 1}",
            coords=list(piece.coords),
            flow_tph=seg.flow_tph,
            role=seg.role,
            method=seg.method,
            k_special=seg.k_special,
            start_node_id=cur_start_node,
            end_node_id=end_node,
            depth_start=round(d_a, 2),
            depth_end=round(d_b, 2),
        )
        part.diameter_mm = seg.diameter_mm
        part.warnings = list(seg.warnings)
        k_avg = (ref.depth_k(d_a) + ref.depth_k(d_b)) / 2.0
        part._tariff_rub_m = seg._tariff_rub_m
        part.cost_rub = seg.cost_rub * (part.length_m / max(seg.length_m, 1e-9)) * k_avg
        part.coords3d = _coords3d(piece, prof, a, b)
        parts.append(part)
        cur_start_node = end_node

    if not parts:  # вырожденный случай — участок как есть
        seg.depth_start = seg.depth_end = base
        seg.coords3d = [(x, y, -base) for x, y in seg.coords]
        parts = [seg]
    return parts


def _depth_at(prof: list[tuple[float, float]], x: float) -> float:
    """Глубина профиля в точке x (линейная интерполяция)."""
    if x <= prof[0][0]:
        return prof[0][1]
    if x >= prof[-1][0]:
        return prof[-1][1]
    for i in range(1, len(prof)):
        if prof[i][0] >= x:
            x0, h0 = prof[i - 1]
            x1, h1 = prof[i]
            t = (x - x0) / max(x1 - x0, 1e-9)
            return h0 + t * (h1 - h0)
    return prof[-1][1]


def _coords3d(piece: LineString, prof, a: float, b: float) -> list:
    """3D-координаты куска: Z = −глубина (м, ниже поверхности)."""
    out = []
    L = piece.length
    for x, y in piece.coords:
        d = piece.project(Point(x, y))
        out.append((x, y, -_depth_at(prof, a + (d if L > 1e-9 else 0.0))))
    return out
