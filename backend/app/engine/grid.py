"""Весовая сетка пространственных ограничений + A* (Спринт 2).

Паттерн растеризации повторяет routing/planner.py (ядро хакатона),
но вес ячейки задаётся ПРАВИЛАМИ техприложения. По техприложению
видов правил ровно два (категории «пересечение с условиями» нет):

  forbidden / min_distance — запрет: ячейки непроходимы, для
                    min_distance непроходим буфер min_distance_m
  special_passage — спецпроход: проходимо с множителем Kспец
                    (берётся из параметров зоны, иначе — тарифный
                    default); ячейки помечаются, чтобы участок
                    выделить отдельно и посчитать по Kспец
"""

from __future__ import annotations

import heapq
import math
from typing import Optional

import numpy as np
from shapely.geometry import Point
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
    """Растр ограничений и поиск пути A* с штрафом за повороты."""

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
        self.zone = np.full((self.nx, self.ny), "", dtype=object)

        self.default_special_mult = float(refdata.tariffs["special_passage_multiplier"])
        self.zone_k: dict[str, float] = {}  # Kспец по ID зоны special_passage
        self.refdata = refdata

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

    def forbidden_reason(self, pt) -> str | None:
        """ID запретной зоны, если точка внутри неё (для §2.9).

        Проверка по ГЕОМЕТРИИ зон (не по растру): A* привязывает цель
        к ближайшей свободной ячейке и «не чувствует» запрет под точкой
        подключения — поэтому явный контроль до маршрутизации.
        """
        for z in getattr(self, "_zones", []):
            if z.kind == "forbidden" and z.geom.intersects(pt):
                return z.object_id
            if z.kind == "min_distance":
                dist = float(z.params.get("min_distance_m")
                             or z.params.get("distance_m") or 10.0)
                if z.geom.buffer(dist).intersects(pt):
                    return z.object_id
        return None

    def apply_constraints(self, zones: list[ConstraintZone]) -> None:
        """Растеризовать ограничения — по техприложению два вида правил."""
        self._zones = zones
        for z in zones:
            if z.kind == "forbidden":
                for c in self._cells_covered_by(z.geom):
                    self.blocked[c] = True
            elif z.kind == "min_distance":
                dist = float(z.params.get("min_distance_m")
                             or z.params.get("distance_m") or 10.0)
                for c in self._cells_covered_by(z.geom.buffer(dist)):
                    self.blocked[c] = True
            elif z.kind == "special_passage":
                k = self._zone_k(z)
                self.zone_k[z.object_id] = k
                for c in self._cells_covered_by(z.geom):
                    if not self.blocked[c]:
                        self.mult[c] = max(self.mult[c], k)
                        self.zone[c] = f"special_passage:{z.object_id}"

    def _zone_k(self, z: ConstraintZone) -> float:
        """Kспец зоны спецпрохода: из параметров зоны, иначе тарифный default."""
        for key in ("k_special", "special_passage_multiplier", "multiplier", "k"):
            v = z.params.get(key)
            if v is not None:
                try:
                    return float(v)
                except (TypeError, ValueError):
                    pass
        return self.default_special_mult

    def penalize_corridor(self, paths, radius_m: float, factor: float) -> list:
        """Временно повысить стоимость ячеек вдоль путей (×factor).

        Нужно для варианта «альтернативный коридор»: A* обходит трассы
        предыдущих вариантов. Возвращает [(ячейка, старый вес)] для
        восстановления через restore_mult.
        """
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
