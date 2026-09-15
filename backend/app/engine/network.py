"""Граф существующей сети по цепочкам «ID следующего объекта» (Спринт 2).

Каждый участок знает ID следующего объекта к источнику теплосети.
Цепочка next_object_id ведёт от любого участка до источника —
это и есть путь для распространения дополнительного расхода (§2.5 ТЗ).
"""

from __future__ import annotations

from typing import Optional

from .model import Chamber, Segment


class ExistingNetwork:
    """Существующая сеть: участки + камеры + навигация к источнику."""

    def __init__(self, segments: dict[str, Segment], chambers: dict[str, Chamber]):
        self.segments = segments
        self.chambers = chambers

    def get(self, object_id: str):
        return self.segments.get(object_id) or self.chambers.get(object_id)

    def chain_to_source(self, start_id: str) -> list[str]:
        """Цепочка object_id от участка до источника (включительно).

        Обрыв (next_object_id отсутствует в наборе) трактуем как
        «достигнут источник» — конец цепочки. Циклы обрезаются.
        """
        chain: list[str] = []
        seen: set[str] = set()
        cur: Optional[str] = start_id
        while cur and cur not in seen:
            seen.add(cur)
            obj = self.get(cur)
            if obj is None:
                break
            chain.append(cur)
            cur = getattr(obj, "next_object_id", None)
        return chain

    def chamber_free_connections(self, chamber_id: str, extra_used: dict[str, int], max_conn: int) -> int:
        """Свободные примыкания камеры с учётом уже назначенных в этом расчёте."""
        chamber = self.chambers.get(chamber_id)
        if chamber is None:
            return 0
        return max(0, max_conn - chamber.occupied_connections - extra_used.get(chamber_id, 0))

    def segments_near(self, point, radius_m: float) -> list[tuple[str, float]]:
        """Участки в радиусе от точки: [(object_id, distance_m)]."""
        out = []
        for sid, seg in self.segments.items():
            d = seg.geom.distance(point)
            if d <= radius_m:
                out.append((sid, d))
        out.sort(key=lambda t: t[1])
        return out

    def chambers_near(self, point, radius_m: float) -> list[tuple[str, float]]:
        out = []
        for cid, ch in self.chambers.items():
            d = ch.geom.distance(point)
            if d <= radius_m:
                out.append((cid, d))
        out.sort(key=lambda t: t[1])
        return out
