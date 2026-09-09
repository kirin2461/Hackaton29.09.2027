"""Ядро трассировки: граф ограничений + A* (Дни 6–10).

Идея:
  1. ГИС-карта растеризуется в регулярную сетку (по умолчанию 10 м).
     Каждая ячейка получает стоимость прохода:
       - ячейка внутри здания        -> непроходима;
       - ячейка пересекает дорогу    -> дорого (множитель);
       - пустырь                     -> дёшево (1.0).
  2. По сетке (8-связный граф) запускается A* с состоянием
     (ячейка, направление движения) — это позволяет штрафовать
     за повороты трубы (инженерное требование теплосетей).
  3. Три профиля весов дают три варианта трассы:
       «Кратчайший», «Экономичный», «В обход дорог».

Новые здания (Точка Б) тоже блокируют ячейки — трасса подводится
к контуру, а не проходит сквозь здание.
"""

from __future__ import annotations

import heapq
import math
from typing import Any

import numpy as np
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import nearest_points
from shapely.prepared import prep

# 8 направлений движения по сетке (кратно 45°).
DIRS = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)]
DIR_DIST = [math.hypot(dx, dy) for dx, dy in DIRS]
NO_DIR = -1  # направление «ещё не двигались» (стартовая ячейка)

DEFAULT_CELL_M = 10.0

# Профили вариантов трассы (День 10).
VARIANT_PROFILES = [
    {"key": "shortest", "name": "Кратчайший", "color": "#74b9ff",
     "road_multiplier": 1.0, "turn_penalty": 0.0},
    {"key": "balanced", "name": "Экономичный", "color": "#00b894",
     "road_multiplier": None, "turn_penalty": None},  # из запроса
    {"key": "no_roads", "name": "В обход дорог", "color": "#e17055",
     "road_multiplier": 50.0, "turn_penalty": 1.0},
]

# Значения по умолчанию для «Экономичного» профиля (бегунки UI).
DEFAULT_TURN_PENALTY = 2.0    # условных метров за каждые 45° поворота
DEFAULT_ROAD_MULTIPLIER = 4.0  # во сколько раз дороже идти по дороге


class RoutePlanner:
    """Весовой граф карты + поиск трассы A*.

    Строится один раз на набор слоёв (нормализованные координаты,
    как в ответе /api/map/layers) и переиспользуется для всех запросов.
    """

    def __init__(self, layers: dict[str, list[dict]],
                 bounds: list[float], cell: float = DEFAULT_CELL_M) -> None:
        self.cell = float(cell)
        minx, miny, maxx, maxy = bounds
        self.ox, self.oy = float(minx), float(miny)
        # Запас в одну ячейку по краям, чтобы точки на границе не вылетали.
        self.nx = int(math.ceil((maxx - minx) / self.cell)) + 2
        self.ny = int(math.ceil((maxy - miny) / self.cell)) + 2

        self.blocked = np.zeros((self.nx, self.ny), dtype=bool)
        self.on_road = np.zeros((self.nx, self.ny), dtype=bool)

        self._rasterize_buildings(layers.get("buildings", []))
        self._rasterize_roads(layers.get("roads", []))

    # ---------- растеризация слоёв ----------

    def _cells_in_bbox(self, minx, miny, maxx, maxy):
        i0 = max(0, int((minx - self.ox) / self.cell))
        j0 = max(0, int((miny - self.oy) / self.cell))
        i1 = min(self.nx - 1, int((maxx - self.ox) / self.cell) + 1)
        j1 = min(self.ny - 1, int((maxy - self.oy) / self.cell) + 1)
        return range(i0, i1 + 1), range(j0, j1 + 1)

    def cell_center(self, i: int, j: int) -> tuple[float, float]:
        return (self.ox + (i + 0.5) * self.cell,
                self.oy + (j + 0.5) * self.cell)

    def _rasterize_buildings(self, features: list[dict]) -> None:
        for f in features:
            poly = Polygon(f["coordinates"])
            if not poly.is_valid or poly.is_empty:
                continue
            prepared = prep(poly)
            xs, ys = self._cells_in_bbox(*poly.bounds)
            for i in xs:
                for j in ys:
                    cx, cy = self.cell_center(i, j)
                    if prepared.covers(Point(cx, cy)):
                        self.blocked[i, j] = True

    def _rasterize_roads(self, features: list[dict]) -> None:
        half = self.cell * 0.55  # дорога «захватывает» ячейку почти целиком
        for f in features:
            line = LineString(f["coordinates"])
            if line.is_empty:
                continue
            band = prep(line.buffer(half))
            xs, ys = self._cells_in_bbox(*line.bounds)
            for i in xs:
                for j in ys:
                    cx, cy = self.cell_center(i, j)
                    if band.covers(Point(cx, cy)):
                        self.on_road[i, j] = True

    # ---------- утилиты ----------

    def to_cell(self, x: float, y: float) -> tuple[int, int]:
        i = min(self.nx - 1, max(0, int((x - self.ox) / self.cell)))
        j = min(self.ny - 1, max(0, int((y - self.oy) / self.cell)))
        return i, j

    def nearest_free(self, cell: tuple[int, int]) -> tuple[int, int] | None:
        """Ближайшая неблокированная ячейка (кольцевой обход)."""
        i0, j0 = cell
        if not self.blocked[i0, j0]:
            return cell
        for radius in range(1, max(self.nx, self.ny)):
            for di in range(-radius, radius + 1):
                for dj in (-radius, radius):
                    for i, j in ((i0 + di, j0 + dj), (i0 + dj, j0 + di)):
                        if 0 <= i < self.nx and 0 <= j < self.ny \
                                and not self.blocked[i, j]:
                            return i, j
        return None

    # ---------- A* со штрафом за повороты (Дни 7 и 9) ----------

    def astar(self, start: tuple[int, int], goal: tuple[int, int],
              road_multiplier: float, turn_penalty: float
              ) -> list[tuple[int, int]] | None:
        """A* по состоянию (i, j, входящее_направление).

        Стоимость шага = стоимость ячейки * длина шага
                       + штраф за поворот (за каждые 45° изменения курса).
        """
        def heuristic(i: int, j: int) -> float:
            return math.hypot(i - goal[0], j - goal[1]) * self.cell

        # g[(i, j, dir)] = лучшая стоимость
        g: dict[tuple[int, int, int], float] = {}
        came: dict[tuple[int, int, int], tuple[int, int, int]] = {}
        start_state = (start[0], start[1], NO_DIR)
        g[start_state] = 0.0
        heap = [(heuristic(*start), 0.0, start_state)]

        best_goal: tuple[int, int, int] | None = None
        while heap:
            f, cost, (i, j, d) = heapq.heappop(heap)
            if cost > g.get((i, j, d), math.inf):
                continue  # устаревшая запись в куче
            if (i, j) == goal:
                best_goal = (i, j, d)
                break
            for nd, (dx, dy) in enumerate(DIRS):
                ni, nj = i + dx, j + dy
                if not (0 <= ni < self.nx and 0 <= nj < self.ny):
                    continue
                if self.blocked[ni, nj]:
                    continue
                step = DIR_DIST[nd] * self.cell
                if self.on_road[ni, nj]:
                    step *= road_multiplier
                if d != NO_DIR:
                    k = abs(nd - d)
                    k = min(k, 8 - k)  # поворот в единицах 45°
                    step += turn_penalty * k * self.cell
                ncost = cost + step
                nstate = (ni, nj, nd)
                if ncost < g.get(nstate, math.inf):
                    g[nstate] = ncost
                    came[nstate] = (i, j, d)
                    heapq.heappush(heap, (ncost + heuristic(ni, nj), ncost, nstate))

        if best_goal is None:
            return None

        path = []
        state: tuple[int, int, int] | None = best_goal
        while state is not None:
            path.append((state[0], state[1]))
            state = came.get(state)
        path.reverse()
        return path

    # ---------- упрощение и метрики пути ----------

    @staticmethod
    def _simplify(cells: list[tuple[int, int]]) -> list[tuple[int, int]]:
        """Убирает промежуточные ячейки на прямых участках."""
        if len(cells) < 3:
            return cells
        out = [cells[0]]
        prev_dir = (cells[1][0] - cells[0][0], cells[1][1] - cells[0][1])
        for a, b in zip(cells[1:], cells[2:]):
            d = (b[0] - a[0], b[1] - a[1])
            if d != prev_dir:
                out.append(a)
                prev_dir = d
        out.append(cells[-1])
        return out

    # ---------- публичный интерфейс ----------

    def plan(self, network_coords: list[list[float]],
             building_polygon: list[list[float]],
             turn_penalty: float = DEFAULT_TURN_PENALTY,
             road_multiplier: float = DEFAULT_ROAD_MULTIPLIER
             ) -> dict[str, Any]:
        """Три варианта трассы от теплосети (Точка А) до здания (Точка Б)."""
        network = LineString(network_coords)
        building = Polygon(building_polygon)
        if not building.is_valid:
            raise ValueError("Некорректный контур здания")

        # Точка врезки (на сети) и точка подключения (на контуре здания).
        p_building, p_network = nearest_points(building, network)

        # Блокируем ячейки НОВОГО здания — трасса не должна его пересекать.
        prep_b = prep(building)
        xs, ys = self._cells_in_bbox(*building.bounds)
        new_blocked = []
        for i in xs:
            for j in ys:
                cx, cy = self.cell_center(i, j)
                if not self.blocked[i, j] and prep_b.covers(Point(cx, cy)):
                    self.blocked[i, j] = True
                    new_blocked.append((i, j))

        try:
            start = self.nearest_free(self.to_cell(p_network.x, p_network.y))
            goal = self.nearest_free(self.to_cell(p_building.x, p_building.y))
            if start is None or goal is None:
                raise ValueError("Не удалось привязать трассу к свободным ячейкам")

            variants = []
            for profile in VARIANT_PROFILES:
                rm = profile["road_multiplier"]
                tp = profile["turn_penalty"]
                if rm is None:
                    rm = road_multiplier
                if tp is None:
                    tp = turn_penalty
                cells = self.astar(start, goal, rm, tp)
                if cells is None:
                    continue
                simple = self._simplify(cells)
                # Координаты: точная врезка -> центры ячеек -> точка на здании.
                pts = [[round(p_network.x, 2), round(p_network.y, 2)]]
                pts += [[round(x, 2), round(y, 2)]
                        for x, y in (self.cell_center(i, j) for i, j in simple)]
                pts.append([round(p_building.x, 2), round(p_building.y, 2)])

                length = sum(
                    math.hypot(b[0] - a[0], b[1] - a[1])
                    for a, b in zip(pts, pts[1:])
                )
                variants.append({
                    "key": profile["key"],
                    "name": profile["name"],
                    "color": profile["color"],
                    "path": pts,
                    "length_m": round(length, 1),
                    "turns": max(0, len(simple) - 1),
                    "params": {"road_multiplier": rm, "turn_penalty": tp},
                })
        finally:
            # Планировщик общий — снимаем временную блокировку здания.
            for i, j in new_blocked:
                self.blocked[i, j] = False

        if not variants:
            raise ValueError("A* не нашёл ни одного пути — проверьте данные слоёв")

        return {
            "variants": variants,
            "connection": {
                "from_point": [round(p_building.x, 2), round(p_building.y, 2)],
                "to_point": [round(p_network.x, 2), round(p_network.y, 2)],
                "length_m": round(float(p_building.distance(p_network)), 1),
            },
            "grid": {"cell_m": self.cell, "nx": self.nx, "ny": self.ny},
        }

