"""Постобработка геометрии трасс (§2.6 ТЗ, Спринт 2).

  - упрощение полилинии (Douglas–Peucker через shapely.simplify);
  - удаление зигзагов/«ступеней» — выбросы с разворотом > max_zigzag_deg;
  - проверка самопересечений новых участков вне общих узлов.
"""

from __future__ import annotations

import math

from shapely.geometry import LineString


def _angle_deg(a, b, c) -> float:
    """Угол поворота в точке b (0° — прямо, 180° — полный разворот)."""
    v1 = (b[0] - a[0], b[1] - a[1])
    v2 = (c[0] - b[0], c[1] - b[1])
    l1, l2 = math.hypot(*v1), math.hypot(*v2)
    if l1 < 1e-9 or l2 < 1e-9:
        return 0.0
    cos = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (l1 * l2)))
    return math.degrees(math.acos(-cos))  # разворот = 180° - угол между векторами


def simplify_path(points: list[tuple[float, float]], tolerance_m: float) -> list[tuple[float, float]]:
    """Выпрямление: упрощение Дугласа–Пекера + удаление зигзагов."""
    if len(points) < 3:
        return points
    line = LineString(points)
    simplified = line.simplify(tolerance_m, preserve_topology=True)
    pts = list(simplified.coords)

    # Удаление зигзагов: точки с разворотом > 150° («елочка» растра)
    max_zigzag = 150.0
    changed = True
    while changed and len(pts) >= 3:
        changed = False
        for i in range(1, len(pts) - 1):
            if _angle_deg(pts[i - 1], pts[i], pts[i + 1]) > max_zigzag:
                del pts[i]
                changed = True
                break
    return [(round(x, 2), round(y, 2)) for x, y in pts]


def check_self_intersection(points: list[tuple[float, float]]) -> bool:
    """True, если полилиния простая (без самопересечений вне узлов)."""
    if len(points) < 4:
        return True
    return LineString(points).is_simple


def crossings_with(line_coords: list[tuple[float, float]], zones) -> list[str]:
    """ID ограничений типа crossing, пересечённых под недопустимым углом.

    Угол считаем между первым пересекающим сегментом и границей/осью зоны;
    зоны-линии — по направлению самой линии, зоны-полигоны — по длиннейшему
    отрезку границы. Упрощённо: по длиннейшему сегменту зоны.
    """
    bad: list[str] = []
    line = LineString(line_coords)
    for z in zones:
        if z.kind != "crossing":
            continue
        min_angle = float(z.params.get("min_angle_deg")
                          or z.params.get("crossing_min_angle_deg") or 45.0)
        inter = line.intersection(z.geom)
        if inter.is_empty:
            continue
        # Эталонное направление зоны: длиннейший отрезок её геометрии
        ref = _longest_direction(z.geom)
        if ref is None:
            continue
        for a, b in zip(line_coords, line_coords[1:]):
            seg = LineString([a, b])
            if not seg.intersects(z.geom):
                continue
            angle = _angle_between((b[0] - a[0], b[1] - a[1]), ref)
            if angle < min_angle:
                bad.append(z.object_id)
                break
    return bad


def _longest_direction(geom):
    coords = None
    if geom.geom_type == "LineString":
        coords = list(geom.coords)
    elif geom.geom_type == "Polygon":
        coords = list(geom.exterior.coords)
    if not coords or len(coords) < 2:
        return None
    best, best_len = None, -1.0
    for a, b in zip(coords, coords[1:]):
        d = (b[0] - a[0], b[1] - a[1])
        L = math.hypot(*d)
        if L > best_len:
            best_len, best = L, d
    return best


def _angle_between(v1, v2) -> float:
    l1, l2 = math.hypot(*v1), math.hypot(*v2)
    if l1 < 1e-9 or l2 < 1e-9:
        return 90.0
    cos = abs((v1[0] * v2[0] + v1[1] * v2[1]) / (l1 * l2))
    return math.degrees(math.acos(min(1.0, cos)))
