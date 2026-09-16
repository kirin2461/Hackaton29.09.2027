"""Граф существующей сети по цепочкам upstream_object_id (§2.2).

Каждый участок/камера знает ID следующего объекта по направлению
к источнику (heat_network, heat_chamber или source). Цепочка ведёт
от любого объекта до источника — это путь распространения
дополнительного расхода для реконструкции (раздел 7).

Число занятых примыканий камеры выводится из ТОПОЛОГИИ (официальная
схема ввода не содержит такого атрибута): участки, указывающие на
камеру как на следующий объект, плюс исходящая цепочка самой камеры.
Если топология не задана — запасной ввод occupied_connections.
"""

from __future__ import annotations

from typing import Optional

from .model import Chamber, Segment, Source


class ExistingNetwork:
    """Существующая сеть: участки + камеры + источники + навигация."""

    def __init__(self, segments: dict[str, Segment],
                 chambers: dict[str, Chamber],
                 sources: Optional[dict[str, Source]] = None):
        self.segments = segments
        self.chambers = chambers
        self.sources = sources or {}

    def get(self, object_id: str):
        return (self.segments.get(object_id)
                or self.chambers.get(object_id)
                or self.sources.get(object_id))

    def chain_to_source(self, start_id: str) -> list[str]:
        """Цепочка object_id от объекта до источника (включительно).

        Обрыв (upstream_object_id отсутствует в наборе) трактуем как
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

    # ---------- камеры ----------

    def chamber_connections(self, chamber_id: str) -> int:
        """Число занятых примыканий камеры — из топологии цепочек.

        Примыкания: участки, для которых камера — следующий объект,
        плюс участок, на который указывает сама камера. Если топология
        не задана совсем — запасной ввод occupied_connections.
        """
        chamber = self.chambers.get(chamber_id)
        if chamber is None:
            return 0
        incoming = sum(1 for s in self.segments.values()
                       if s.next_object_id == chamber_id)
        outgoing = 1 if chamber.next_object_id in self.segments else 0
        topo = incoming + outgoing
        # официальная схема ввода не несёт occupied_connections (0) —
        # тогда работает топология; для внутренних наборов с явным
        # значением берётся оно
        return max(topo, chamber.occupied_connections)

    def chamber_free_connections(self, chamber_id: str, extra_used: dict[str, int],
                                 max_conn: int) -> int:
        """Свободные примыкания с учётом назначенных в этом расчёте."""
        if chamber_id not in self.chambers:
            return 0
        used = self.chamber_connections(chamber_id) + extra_used.get(chamber_id, 0)
        return max(0, max_conn - used)

    def chamber_adjacent_segment_ids(self, chamber_id: str) -> list[str]:
        """ID участков, примыкающих к камере (обе стороны цепочки)."""
        ids = [sid for sid, s in self.segments.items()
               if s.next_object_id == chamber_id]
        ch = self.chambers.get(chamber_id)
        if ch and ch.next_object_id in self.segments:
            ids.append(ch.next_object_id)
        return ids

    # ---------- геометрический поиск ----------

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
