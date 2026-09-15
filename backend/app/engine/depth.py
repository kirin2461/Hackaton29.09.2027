"""Задание на глубину (доп. задача, Спринт 4): вертикальный профиль трассы.

Для каждого нового участка строится отметка глубины заложения (Z):
  - целевая глубина = базовая + добавка по диаметру (все значения — из
    reference.yaml, секция depth; §2.14: констант в коде нет);
  - отметки дискретизируются шагом step_m (0.5 м по заданию на глубину);
  - продольный уклон при смене глубины ограничен max_slope_pct — переход
    между отметками растягивается на минимально допустимую длину;
  - участки глубже deep_threshold_m считаются «глубокими»: стоимость
    земляных работ растёт (deep_multiplier), факт уходит в warnings и
    в свойства результата.

Z записывается в координаты GeoJSON (третья координата, метры,
отрицательная — ниже поверхности земли).
"""

from __future__ import annotations

import math

from .hydraulics import NewSegment
from .refdata import RefData


def target_depth_m(dn_mm: float, ref: RefData) -> float:
    """Целевая глубина заложения для диаметра, квантованная шагом."""
    base = ref.depth_rule("base_depth_m", 1.5)
    extra = ref.depth_for_diameter(dn_mm)
    step = ref.depth_rule("step_m", 0.5)
    return round(round((base + extra) / step) * step, 3)


def assign_depth(seg: NewSegment, ref: RefData,
                 entry_depth_m: float | None = None) -> None:
    """Проставить глубину участку: coords3d, depth_m, пересчёт стоимости.

    entry_depth_m — отметка в точке подключения (от вышележащего
    участка/камеры). Если она глубже целевой, участок «дотягивается»
    до неё с учётом ограничения продольного уклона.
    """
    target = target_depth_m(seg.diameter_mm, ref)
    step = ref.depth_rule("step_m", 0.5)
    max_slope = ref.depth_rule("max_slope_pct", 10.0) / 100.0

    depths = [target] * len(seg.coords)
    if entry_depth_m is not None and entry_depth_m > target:
        # Переход от глубокой точки подключения к целевой отметке
        # с ограничением уклона: протяжённость пандуса = Δh / slope.
        ramp_len = (entry_depth_m - target) / max(max_slope, 1e-6)
        acc = 0.0
        prev = seg.coords[0]
        depths[0] = entry_depth_m
        for i in range(1, len(seg.coords)):
            acc += math.hypot(seg.coords[i][0] - prev[0],
                              seg.coords[i][1] - prev[1])
            prev = seg.coords[i]
            if acc >= ramp_len:
                break
            # линейный спуск по длине пандуса, квантование шагом
            d = entry_depth_m - (entry_depth_m - target) * (acc / ramp_len)
            depths[i] = round(round(d / step) * step, 3)
    seg.depth_m = max(depths)
    seg.coords3d = [(x, y, -z) for (x, y), z in zip(seg.coords, depths)]

    threshold = ref.depth_rule("deep_threshold_m", 3.5)
    if seg.depth_m > threshold:
        mult = ref.depth_rule("deep_multiplier", 1.25)
        seg.cost_rub *= mult
        seg.warnings.append(
            f"глубокая прокладка {seg.depth_m:.1f} м (> {threshold:.1f} м): "
            f"стоимость ×{mult:.2f}"
        )


def chamber_depth_m(ref: RefData, connecting_dn_mm: float | None = None) -> float:
    """Отметка дна камеры: глубина примыкающего участка + перепад."""
    base = target_depth_m(connecting_dn_mm, ref) if connecting_dn_mm \
        else ref.depth_rule("base_depth_m", 1.5)
    return round(base + ref.depth_rule("chamber_drop_m", 0.5), 3)
