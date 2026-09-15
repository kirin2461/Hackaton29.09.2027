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
