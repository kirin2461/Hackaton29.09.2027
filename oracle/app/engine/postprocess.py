"""Постобработка геометрии трасс (§2.6 ТЗ).

  - упрощение полилинии (Douglas–Peucker через shapely.simplify);
  - удаление зигзагов/«ступеней» — выбросы с разворотом > max_zigzag_deg;
  - проверка самопересечений новых участков вне общих узлов;
  - контроль угла пересечения дорог/трамваев (таблица 5.1: не менее 45°).
"""

from __future__ import annotations

import math

from shapely.geometry import LineString, Point


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


# ---------------------------------------------------------------------------
# Угол пересечения (таблица 5.1: road / tram_tracks — не менее 45°)
# ---------------------------------------------------------------------------

def crossing_angle_deg(line: LineString, zone_geom) -> float | None:
    """Угол пересечения трассы с зоной (0–90°). None — пересечения нет.

    Для полигонов направление зоны — главная ось минимального
    повёрнутого прямоугольника; для линий — направление в точке
    пересечения. Направление трассы — хорда участка пересечения.
    """
    if not line.intersects(zone_geom):
        return None
    inter = line.intersection(zone_geom)
    chord = _chord_direction(inter if inter.length > 1e-6 else line)
    if chord is None:
        return None
    if zone_geom.geom_type in ("Polygon", "MultiPolygon"):
        zone_dir = _rect_direction(zone_geom.minimum_rotated_rectangle)
    else:
        zone_dir = _chord_direction(zone_geom)
    if zone_dir is None:
        return None
    dot = abs(chord[0] * zone_dir[0] + chord[1] * zone_dir[1])
    return math.degrees(math.acos(max(-1.0, min(1.0, dot))))


def _chord_direction(geom) -> tuple[float, float] | None:
    """Единичный вектор направления по хорде «первая—последняя точка»."""
    t = geom.geom_type
    if t == "LineString":
        coords = list(geom.coords)
    elif t == "MultiLineString":
        coords = [c for g in geom.geoms for c in g.coords]
    elif t == "Point":
        return None
    else:
        try:
            coords = list(geom.boundary.coords)
        except Exception:
            return None
    if len(coords) < 2:
        return None
    dx, dy = coords[-1][0] - coords[0][0], coords[-1][1] - coords[0][1]
    l = math.hypot(dx, dy)
    if l < 1e-9:
        return None
    return (dx / l, dy / l)


def _rect_direction(rect) -> tuple[float, float] | None:
    """Направление длинной стороны минимального повёрнутого прямоугольника."""
    coords = list(rect.exterior.coords)[:4]
    best = None
    best_len = -1.0
    for a, b in zip(coords, coords[1:]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        l = math.hypot(dx, dy)
        if l > best_len:
            best_len = l
            best = (dx / l, dy / l) if l > 1e-9 else None
    return best


def check_crossing_angles(line: LineString, special_zones: list,
                          warnings: list, owner: str) -> None:
    """Предупреждение, если пересечение дороги/трамвая острее 45°."""
    for z in special_zones:
        rtype = getattr(z, "restriction_type", None)
        if rtype not in ("road", "tram_tracks"):
            continue
        angle = crossing_angle_deg(line, z.geom)
        if angle is not None and angle < 45.0:
            warnings.append(
                f"{owner}: пересечение {z.object_id} ({rtype}) под углом "
                f"{angle:.0f}° < 45° (таблица 5.1)")
