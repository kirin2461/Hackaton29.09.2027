"""Многокритериальный выбор трассы: Парето-фронт «цена ↔ надёжность».

У трассы два конфликтующих критерия:
  - стоимость строительства (млн ₽) — чем длиннее и извилистее,
    тем дороже;
  - ущерб живучести сети — N-1 после врезки: доля тепла, которая
    пропадёт при отказе худшего сегмента (чем больше сеть «растёт
    в хвост», тем хуже).

Бегунки UI крутят веса вручную и нащупывают один компромисс.
Здесь мы честно сканируем пространство весов (штраф за поворот ×
множитель дороги), собираем все различные трассы, считаем оба
критерия и строим Парето-фронт: множество вариантов, которые
нельзя улучшить по одному критерию без ухудшения другого.
Все доминируемые варианты жюри видит серыми точками.
"""

from __future__ import annotations

from typing import Any

from .estimate import validate_path
from .netstats import impact as network_impact
from .netstats import reliability
from .planner import RoutePlanner

# Сетка весов для сканирования пространства компромиссов.
TURN_PENALTIES = (0.0, 2.0, 8.0)
ROAD_MULTIPLIERS = (1.0, 4.0, 16.0)


def _path_key(path: list[list[float]]) -> tuple:
    return tuple((round(x, 1), round(y, 1)) for x, y in path)


def _pareto_mask(points: list[dict]) -> list[bool]:
    """True для недоминируемых точек (минимизируем оба критерия)."""
    order = sorted(range(len(points)),
                   key=lambda i: (points[i]["cost_mln_rub"],
                                  points[i]["n1_after_pct"]))
    front = []
    best_y = float("inf")
    for i in order:
        if points[i]["n1_after_pct"] < best_y - 1e-9:
            front.append(i)
            best_y = points[i]["n1_after_pct"]
    mask = [False] * len(points)
    for i in front:
        mask[i] = True
    return mask


def build_pareto(layers: dict[str, list[dict]],
                 planner: RoutePlanner,
                 network_coords: list[list[float]],
                 polygon: list[list[float]]) -> dict[str, Any]:
    """Сканирует веса A* и возвращает точки + фронт Парето."""
    seen: set[tuple] = set()
    points: list[dict] = []

    for tp in TURN_PENALTIES:
        for rm in ROAD_MULTIPLIERS:
            try:
                res = planner.plan(network_coords, polygon,
                                   turn_penalty=tp, road_multiplier=rm)
            except ValueError:
                continue
            for v in res["variants"]:
                key = _path_key(v["path"])
                if key in seen:
                    continue
                seen.add(key)
                est = validate_path(v["path"], layers)
                if est["collision"]:
                    continue
                rel = reliability(
                    [f["coordinates"] for f in layers.get("heat_networks", [])],
                    v["path"], mc_trials=0)  # только N-1, быстро
                imp = network_impact(
                    [f["coordinates"] for f in layers.get("heat_networks", [])],
                    v["path"])
                points.append({
                    "key": f"pareto_{len(points) + 1}",
                    "path": v["path"],
                    "length_m": est["length_m"],
                    "turns": est["turns"],
                    "road_crossings": est["road_crossings"],
                    "cost_mln_rub": est["cost_mln_rub"],
                    "n1_after_pct": rel["n1_worst_pct"],
                    "entropy_delta": imp["delta"]["entropy_norm"],
                    "params": {"turn_penalty": tp, "road_multiplier": rm},
                })

    if not points:
        raise ValueError("Не удалось построить ни одной трассы")

    mask = _pareto_mask(points)
    for p, on_front in zip(points, mask):
        p["is_pareto"] = on_front

    return {
        "points": points,
        "front": [p["key"] for p in points if p["is_pareto"]],
        "x_axis": {"key": "cost_mln_rub", "name": "Стоимость, млн ₽"},
        "y_axis": {"key": "n1_after_pct",
                   "name": "N-1 после врезки, % тепла без подачи"},
    }
