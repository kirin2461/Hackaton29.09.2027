"""Выбор точек врезки в существующую сеть (§2.3–2.5 ТЗ, Спринт 2).

Кандидаты:
  1) существующая камера со свободными примыканиями (лимит — 4,
     из них в новых направлениях — 3);
  2) проекция на трубопровод → строительство НОВОЙ камеры в точке врезки.

Победитель — минимальная полная стоимость «длина подводки + врезка».
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from shapely.geometry import Point

from .model import Building
from .network import ExistingNetwork
from .refdata import RefData


@dataclass
class Tap:
    """Выбранная точка врезки."""

    kind: str                # "existing_chamber" | "new_chamber_on_segment"
    point: Point             # точка врезки (метрическая СК)
    flow_tph: float          # расход, который войдёт в сеть в этой точке
    chamber_id: Optional[str] = None      # для existing_chamber
    segment_id: Optional[str] = None      # для new_chamber_on_segment
    chain_start_id: Optional[str] = None  # с чего начинать цепочку к источнику
    tap_cost_rub: float = 0.0


def choose_tap(anchor: Point, flow_tph: float, net: ExistingNetwork,
               refdata: RefData, chamber_load: dict[str, int]) -> Optional[Tap]:
    """Лучшая точка врезки для здания/кластера от точки anchor."""
    radius = refdata.rule("tap_search_radius_m")
    max_conn = int(refdata.rule("max_chamber_connections"))
    lay_min = refdata.lay_tariff(refdata.diameter_for_flow(flow_tph)["dn_mm"])

    best: Optional[Tap] = None
    best_cost = float("inf")

    # --- кандидат 1: существующие камеры ---
    for cid, dist in net.chambers_near(anchor, radius):
        if net.chamber_free_connections(cid, chamber_load, max_conn) <= 0:
            continue
        cost = dist * lay_min + refdata.tariff("tapping_existing_chamber")
        if cost < best_cost:
            ch = net.chambers[cid]
            best_cost = cost
            best = Tap(
                kind="existing_chamber",
                point=ch.geom,
                flow_tph=flow_tph,
                chamber_id=cid,
                chain_start_id=cid,
                tap_cost_rub=refdata.tariff("tapping_existing_chamber"),
            )

    # --- кандидат 2: проекция на трубопровод → новая камера ---
    for sid, dist in net.segments_near(anchor, radius):
        seg = net.segments[sid]
        proj_m = seg.geom.project(anchor)
        pt = seg.geom.interpolate(proj_m)
        real_dist = pt.distance(anchor)
        cost = real_dist * lay_min + refdata.tariff("chamber_new")
        if cost < best_cost:
            best_cost = cost
            best = Tap(
                kind="new_chamber_on_segment",
                point=pt,
                flow_tph=flow_tph,
                segment_id=sid,
                chain_start_id=sid,
                tap_cost_rub=refdata.tariff("chamber_new"),
            )

    return best
