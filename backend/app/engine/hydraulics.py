"""Гидравлика новой сети: расходы, диаметры, предельные длины (§2.4 ТЗ).

  - расходы суммируются на общих участках (ствол несёт сумму ветвей);
  - диаметр — минимальный Ду по справочнику пропускной способности;
  - предельная длина непрерывной части одного диаметра: при превышении
    участок делится техническим узлом, отсчёт длины начинается заново.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from shapely.geometry import LineString, Point

from .refdata import RefData


@dataclass
class NewSegment:
    """Новый участок сети (ствол, ветвь, спецпроходный кусок)."""

    object_id: str
    coords: list[tuple[float, float]]
    flow_tph: float
    role: str = "branch"          # trunk | branch
    method: str = "open_trench"   # open_trench | special_passage
    k_special: float | None = None  # Kспец зоны спецпрохода (None — тарифный default)
    diameter_mm: float = 0.0
    length_m: float = 0.0
    cost_rub: float = 0.0
    warnings: list = field(default_factory=list)
    depth_m: float = 0.0              # максимальная глубина заложения (Спринт 4)
    coords3d: list | None = None      # координаты с Z (м, отрицательные)

    def __post_init__(self):
        self.length_m = _path_length(self.coords)


@dataclass
class TechnicalNode:
    """Технический узел на границе предельной длины диаметра."""

    object_id: str
    point: Point
    reason: str


def _path_length(coords) -> float:
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(coords, coords[1:]))


def size_segment(seg: NewSegment, refdata: RefData) -> None:
    """Подобрать диаметр и посчитать базовую стоимость участка."""
    d = refdata.diameter_for_flow(seg.flow_tph)
    seg.diameter_mm = d["dn_mm"]
    if d["max_flow_tph"] < seg.flow_tph:
        seg.warnings.append(
            f"расход {seg.flow_tph} т/ч превышает справочный максимум {d['max_flow_tph']} т/ч"
        )
    tariff = refdata.lay_tariff(seg.diameter_mm)
    if seg.method == "special_passage":
        tariff *= seg.k_special or refdata.tariffs["special_passage_multiplier"]
    seg.cost_rub = seg.length_m * tariff


def enforce_max_length(seg: NewSegment, refdata: RefData, node_seq: list,
                       node_prefix: str = "tech") -> tuple[list[NewSegment], list[TechnicalNode]]:
    """Контроль предельной длины непрерывной части одного диаметра.

    Возвращает (список подучастков, список техузлов). Если длина в пределах
    нормы — возвращается исходный участок без изменений.
    """
    max_len = refdata.max_len_for(seg.diameter_mm)
    if seg.length_m <= max_len:
        return [seg], []

    line = LineString(seg.coords)
    parts: list[NewSegment] = []
    nodes: list[TechnicalNode] = []
    offset = 0.0
    part_idx = 1
    while offset < seg.length_m - 1e-6:
        end = min(offset + max_len, seg.length_m)
        sub = _subline(line, offset, end)
        sub_seg = NewSegment(
            object_id=f"{seg.object_id}#{part_idx}",
            coords=list(sub.coords),
            flow_tph=seg.flow_tph,
            role=seg.role,
            method=seg.method,
            k_special=seg.k_special,
        )
        sub_seg.diameter_mm = seg.diameter_mm
        tariff = refdata.lay_tariff(seg.diameter_mm)
        if seg.method == "special_passage":
            tariff *= seg.k_special or refdata.tariffs["special_passage_multiplier"]
        sub_seg.cost_rub = sub_seg.length_m * tariff
        parts.append(sub_seg)
        if end < seg.length_m - 1e-6:
            node_seq[0] += 1
            nodes.append(TechnicalNode(
                object_id=f"{node_prefix}-{node_seq[0]}",
                point=line.interpolate(end),
                reason=f"предельная длина Ду{int(seg.diameter_mm)} ({int(max_len)} м)",
            ))
            cost_node = refdata.tariff("technical_node")
            parts[-1].cost_rub += cost_node  # стоимость узла — в предшествующий подучасток
        offset = end
        part_idx += 1
    return parts, nodes


def _subline(line: LineString, start_m: float, end_m: float) -> LineString:
    """Кусок полилинии между двумя отметками длины."""
    n = 32
    pts = [line.interpolate(start_m + (end_m - start_m) * k / n) for k in range(n + 1)]
    return LineString([(p.x, p.y) for p in pts])
