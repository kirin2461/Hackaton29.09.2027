"""Весовая сетка пространственных ограничений + A* (таблица 5.1).

Правила техприложения (таблица 5.1):

  forbidden — пересечение запрещено: геометрия зоны непроходима,
              а МИНИМАЛЬНОЕ РАССТОЯНИЕ (для oks_existing — 5/7/9 м по Ду
              новой сети, для park/social_area/prohibited_site/water —
              1,0 м) обеспечивается ВРЕМЕННЫМИ буферными блокировками
              под конкретный диаметр прокладываемой трассы
              (clearance_block/dn). Расстояние считается между ГРАНЯМИ
              расчётных габаритов (таблица 4.2), поэтому к отступу
              добавляется половина ширины пары труб.

  special_passage — спецпроход: проходимо с множителем Kспец зоны;
              границы спецучастка: для полигональных зон (road,
              tram_tracks) — полигон + extent_m с каждой стороны, для
              линейных/точечных (gas_pipeline, power_cable,
              heat_network) — ±extent_m от точки пересечения
              (special_intervals).
"""

from __future__ import annotations

import heapq
import math
from typing import Optional

import numpy as np
from shapely.geometry import LineString, Point
from shapely.prepared import prep

from .model import ConstraintZone
from .refdata import RefData

# 8 направлений: (di, dj, длина шага в ячейках)
_NEIGHBOURS = [
    (1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
    (1, 1, math.sqrt(2)), (1, -1, math.sqrt(2)),
    (-1, 1, math.sqrt(2)), (-1, -1, math.sqrt(2)),
]


class ConstraintGrid:
    """Растр ограничений и поиск пути A* со штрафом за повороты."""

    def __init__(self, bounds: tuple, refdata: RefData):
        cell = float(refdata.rule("grid_cell_m"))
        self.cell = cell
        minx, miny, maxx, maxy = bounds
        pad = cell * 4  # запас по краям
        self.ox, self.oy = minx - pad, miny - pad
        self.nx = int(math.ceil((maxx - minx + 2 * pad) / cell)) + 1
        self.ny = int(math.ceil((maxy - miny + 2 * pad) / cell)) + 1

        self.blocked = np.zeros((self.nx, self.ny), dtype=bool)
        self.mult = np.ones((self.nx, self.ny), dtype=np.float32)

        self.refdata = refdata
        self.zone_k: dict[str, float] = {}        # Kспец по ID зоны спецпрохода
        self.special_zones: list[ConstraintZone] = []
        self.forbidden_zones: list[ConstraintZone] = []
        self._clearance_cache: dict[tuple[str, int], object] = {}

    # ---------- растеризация ----------

    def _cells_covered_by(self, geom) -> list[tuple[int, int]]:
        minx, miny, maxx, maxy = geom.bounds
        i0 = max(0, int((minx - self.ox) / self.cell) - 1)
        j0 = max(0, int((miny - self.oy) / self.cell) - 1)
        i1 = min(self.nx - 1, int((maxx - self.ox) / self.cell) + 2)
        j1 = min(self.ny - 1, int((maxy - self.oy) / self.cell) + 2)
        prepared = prep(geom)
        cells = []
        for i in range(i0, i1 + 1):
            for j in range(j0, j1 + 1):
                if prepared.covers(Point(self.cell_center(i, j))):
                    cells.append((i, j))
        return cells

    def apply_constraints(self, zones: list[ConstraintZone]) -> None:
        """Растеризовать ограничения: запретные — геометрия, спец — Kспец."""
        for z in zones:
            if z.kind == "forbidden":
                self.forbidden_zones.append(z)
                for c in self._cells_covered_by(z.geom):
                    self.blocked[c] = True
            elif z.kind == "special_passage":
                rule = self.refdata.restriction_rule(z.restriction_type) or {}
                k = float(rule.get("k_special", 1.5))
                self.zone_k[z.object_id] = k
                self.special_zones.append(z)
                for c in self._cells_covered_by(z.geom):
                    if not self.blocked[c]:
                        self.mult[c] = max(self.mult[c], k)

    # ---------- отступы запретных зон под диаметр (таблица 5.1) ----------

    def clearance_buffer_geom(self, zone: ConstraintZone, dn_mm: float):
        """Буферная геометрия: отступ + половина ширины габарита (между гранями)."""
        key = (zone.object_id, int(dn_mm))
        if key not in self._clearance_cache:
            dist = self.refdata.min_distance_m(zone.restriction_type or "", dn_mm)
            dist += self.refdata.envelope_width_m(dn_mm) / 2.0
            self._clearance_cache[key] = zone.geom.buffer(dist)
        return self._clearance_cache[key]

    def clearance_block(self, dn_mm: float) -> list[tuple[int, int]]:
        """Временно заблокировать отступы запретных зон под диаметр трассы.

        Возвращает список ячеек для последующего clearance_unblock.
        """
        cells: list[tuple[int, int]] = []
        for z in self.forbidden_zones:
            buf = self.clearance_buffer_geom(z, dn_mm)
            for c in self._cells_covered_by(buf):
                if not self.blocked[c]:
                    self.blocked[c] = True
                    cells.append(c)
        return cells

    def clearance_unblock(self, cells) -> None:
        for c in cells:
            self.blocked[c] = False

    def forbidden_reason(self, pt, dn_mm: float | None = None) -> str | None:
        """ID запретной зоны, если точка внутри неё/её отступа (для §2.9).

        Проверка по ГЕОМЕТРИИ зон (не по растру): A* привязывает цель
        к ближайшей свободной ячейке и «не чувствует» запрет под точкой
        подключения — поэтому явный контроль до маршрутизации.
        """
        for z in self.forbidden_zones:
            if dn_mm is not None:
                if self.clearance_buffer_geom(z, dn_mm).intersects(pt):
                    return z.object_id
            elif z.geom.intersects(pt):
                return z.object_id
        return None

    # ---------- границы спецучастков (таблица 5.1) ----------

    def special_intervals(self, line: LineString) -> list[tuple[float, float, str, float]]:
        """Интервалы спецпрохода вдоль линии: [(start_m, end_m, zone_id, k)].

        Полигональные зоны (road, tram_tracks): пересечение с полигоном,
        расширенное на extent_m с каждой стороны. Линейные/точечные
        (gas_pipeline, power_cable, heat_network): ±extent_m от каждой
        точки пересечения. Наложения объединяются (берётся max Kспец).
        """
        length = line.length
        if length < 1e-6 or not self.special_zones:
            return []
        raw: list[tuple[float, float, str, float]] = []
        for z in self.special_zones:
            if not line.intersects(z.geom):
                continue
            rule = self.refdata.restriction_rule(z.restriction_type) or {}
            extent = float(rule.get("extent_m", 0.0))
            k = self.zone_k.get(z.object_id, float(rule.get("k_special", 1.5)))
            mode = rule.get("extent_mode", "polygon")
            if mode == "polygon" or z.geom.geom_type in ("Polygon", "MultiPolygon"):
                inter = line.intersection(z.geom)
                pts = _interval_points(inter)
                if not pts:
                    continue
                a = min(line.project(Point(p)) for p in pts)
                b = max(line.project(Point(p)) for p in pts)
                raw.append((max(0.0, a - extent), min(length, b + extent),
                            z.object_id, k))
            else:
                inter = line.intersection(z.geom)
                for p in _interval_points(inter):
                    d = line.project(Point(p))
                    raw.append((max(0.0, d - extent), min(length, d + extent),
                                z.object_id, k))
        return _merge_intervals(raw)

    # ---------- вариант «альтернативный коридор» ----------

    def penalize_corridor(self, paths, radius_m: float, factor: float) -> list:
        """Временно повысить стоимость ячеек вдоль путей (×factor)."""
        cells: set[tuple[int, int]] = set()
        r = int(math.ceil(radius_m / self.cell))
        for pts in paths:
            for x, y in pts:
                ci, cj = self.to_cell(x, y)
                for i in range(ci - r, ci + r + 1):
                    for j in range(cj - r, cj + r + 1):
                        if 0 <= i < self.nx and 0 <= j < self.ny:
                            cells.add((i, j))
        changed = []
        for c in cells:
            if not self.blocked[c]:
                changed.append((c, float(self.mult[c])))
                self.mult[c] *= factor
        return changed

    def restore_mult(self, changed: list) -> None:
        for c, old in changed:
            self.mult[c] = old

    def block_polygon(self, geom) -> list[tuple[int, int]]:
        """Временная блокировка (например, контур целевого ОКС)."""
        cells = [c for c in self._cells_covered_by(geom) if not self.blocked[c]]
        for c in cells:
            self.blocked[c] = True
        return cells

    def unblock(self, cells) -> None:
        for c in cells:
            self.blocked[c] = False

    # ---------- координаты ----------

    def cell_center(self, i: int, j: int) -> tuple[float, float]:
        return self.ox + (i + 0.5) * self.cell, self.oy + (j + 0.5) * self.cell

    def to_cell(self, x: float, y: float) -> tuple[int, int]:
        i = min(max(0, int((x - self.ox) / self.cell)), self.nx - 1)
        j = min(max(0, int((y - self.oy) / self.cell)), self.ny - 1)
        return (i, j)

    def nearest_free(self, cell: tuple[int, int]) -> Optional[tuple[int, int]]:
        if not self.blocked[cell]:
            return cell
        for r in range(1, 40):
            ci, cj = cell
            for di in range(-r, r + 1):
                for dj in (-r, r):
                    for cand in ((ci + di, cj + dj), (ci + dj, cj + di)):
                        if 0 <= cand[0] < self.nx and 0 <= cand[1] < self.ny \
                                and not self.blocked[cand]:
                            return cand
        return None

    # ---------- A* ----------

    def astar(self, start_xy, goal_xy, turn_penalty_m: Optional[float] = None) -> Optional[list[tuple[float, float]]]:
        """Путь между точками (метрическая СК). None — путь не найден."""
        tp = turn_penalty_m if turn_penalty_m is not None else self.refdata.rule("turn_penalty_m")
        start = self.nearest_free(self.to_cell(*start_xy))
        goal = self.nearest_free(self.to_cell(*goal_xy))
        if start is None or goal is None:
            return None

        gc, hc = self.cell_center(*goal)
        open_heap = [(0.0, 0.0, start, None)]  # f, g, cell, (parent, dir_idx)
        came: dict[tuple[int, int], tuple] = {}
        best_g = {start: 0.0}
        directions = {start: -1}

        while open_heap:
            _, g, cur, _ = heapq.heappop(open_heap)
            if cur == goal:
                cells = [cur]
                while cur in came:
                    cur, _ = came[cur]
                    cells.append(cur)
                cells.reverse()
                return [self.cell_center(i, j) for i, j in cells]

            cur_dir = directions.get(cur, -1)
            cx, cy = self.cell_center(*cur)
            for dir_idx, (di, dj, step) in enumerate(_NEIGHBOURS):
                nb = (cur[0] + di, cur[1] + dj)
                if not (0 <= nb[0] < self.nx and 0 <= nb[1] < self.ny):
                    continue
                if self.blocked[nb]:
                    continue
                nx_, ny_ = self.cell_center(*nb)
                move = math.hypot(nx_ - cx, ny_ - cy) * (self.mult[cur] + self.mult[nb]) / 2.0
                if cur_dir >= 0 and dir_idx != cur_dir:
                    move += tp  # штраф за смену направления
                ng = g + move
                if ng < best_g.get(nb, math.inf):
                    best_g[nb] = ng
                    came[nb] = (cur, dir_idx)
                    directions[nb] = dir_idx
                    h = math.hypot(nx_ - gc, ny_ - hc)
                    heapq.heappush(open_heap, (ng + h, ng, nb, (cur, dir_idx)))
        return None


# ---------------------------------------------------------------------------
# Утилиты интервалов спецпрохода
# ---------------------------------------------------------------------------

def _interval_points(geom) -> list[tuple[float, float]]:
    """Точки геометрии пересечения (для project вдоль линии)."""
    t = geom.geom_type
    if t == "Point":
        return [(geom.x, geom.y)]
    if t == "MultiPoint":
        return [(p.x, p.y) for p in geom.geoms]
    if t == "LineString":
        return list(geom.coords)
    if t in ("MultiLineString", "GeometryCollection"):
        pts: list[tuple[float, float]] = []
        geoms = geom.geoms if t == "MultiLineString" else geom.geoms
        for g in geoms:
            pts.extend(_interval_points(g))
        return pts
    if t in ("Polygon", "MultiPolygon"):
        return [(geom.representative_point().x, geom.representative_point().y)]
    return []


def _merge_intervals(raw: list[tuple[float, float, str, float]]) -> list[tuple[float, float, str, float]]:
    """Объединить пересекающиеся интервалы (Kспец — максимальный)."""
    if not raw:
        return []
    raw.sort(key=lambda iv: iv[0])
    merged = [list(raw[0])]
    for a, b, zid, k in raw[1:]:
        last = merged[-1]
        if a <= last[1] + 1e-6:
            last[1] = max(last[1], b)
            if k > last[3]:
                last[2], last[3] = zid, k
        else:
            merged.append([a, b, zid, k])
    return [(a, b, zid, k) for a, b, zid, k in merged]
