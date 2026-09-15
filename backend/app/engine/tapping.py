"""Выбор точки врезки в существующую сеть — строгое правило §8.2.

Никакой эвристики ранжирования кандидатов. Детерминированно:

  1) если от точки подключения до существующей камеры ≤ 10 м
     (`chamber_tap_max_dist_m`) и у камеры меньше 4 примыкающих
     участков (`max_chamber_connections`, считая уже назначенные
     в этом расчёте) — врезка в эту камеру (ближайшую из подходящих);
  2) иначе — строительство НОВОЙ камеры на ближайшей проекции
     точки подключения на существующий участок сети (в радиусе
     `tap_search_radius_m`); если участков в радиусе нет — None
     (ОКС уйдёт в unconnected, §2.9).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from shapely.geometry import Point

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


def choose_tap_strict(anchor: Point, flow_tph: float, net: ExistingNetwork,
                      refdata: RefData, chamber_load: dict[str, int]) -> Optional[Tap]:
    """Точка врезки по §8.2 для здания/кластера от точки anchor."""
    max_dist = float(refdata.rule("chamber_tap_max_dist_m"))
    max_conn = int(refdata.rule("max_chamber_connections"))

    # --- шаг 1: камера ≤ 10 м со свободными примыканиями ---
    best: tuple[float, str] | None = None
    for cid, dist in net.chambers_near(anchor, max_dist):
        if net.chamber_free_connections(cid, chamber_load, max_conn) <= 0:
            continue  # камера рядом, но примыканий уже 4 — новая камера
        if best is None or dist < best[0]:
            best = (dist, cid)
    if best is not None:
        ch = net.chambers[best[1]]
        return Tap(
            kind="existing_chamber",
            point=ch.geom,
            flow_tph=flow_tph,
            chamber_id=best[1],
            chain_start_id=best[1],
            tap_cost_rub=refdata.tariff("tapping_existing_chamber"),
        )

    # --- шаг 2: новая камера на ближайшей проекции на участок ---
    near = net.segments_near(anchor, float(refdata.rule("tap_search_radius_m")))
    if not near:
        return None
    sid, _ = near[0]
    seg = net.segments[sid]
    pt = seg.geom.interpolate(seg.geom.project(anchor))
    return Tap(
        kind="new_chamber_on_segment",
        point=pt,
        flow_tph=flow_tph,
        segment_id=sid,
        chain_start_id=sid,
        tap_cost_rub=refdata.tariff("chamber_new"),
    )
