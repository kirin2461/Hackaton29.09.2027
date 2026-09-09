"""Обратная задача: поиск лучших площадок под новое здание.

Классический поток: «есть здание — проведи трубу». Мы переворачиваем
постановку: сервис сканирует все свободные участки квартала, для
каждого строит трассу A* и считает стоимость технологического
присоединения. Результат — рейтинг площадок: где в квартале выгоднее
всего разместить новое здание с точки зрения теплосетей.

Площадка отбраковывается, если:
  - пересекается с существующей застройкой (с запасом 5 м);
  - наезжает на дорогу;
  - дальше max_dist от теплосети (дальние подключения невыгодны
    по определению) или вплотную к трубе (<60 м — тривиальный случай).
"""

from __future__ import annotations

import math
from typing import Any

from shapely.geometry import LineString, Point, Polygon, box
from shapely.prepared import prep

from .estimate import validate_path
from .netstats import impact as network_impact
from .netstats import reliability
from .planner import DEFAULT_ROAD_MULTIPLIER, DEFAULT_TURN_PENALTY, RoutePlanner

# Пороги отбора площадок.
MIN_DIST_TO_NETWORK_M = 60.0   # ближе — тривиальная врезка
MAX_DIST_TO_NETWORK_M = 500.0  # дальше — заведомо дорого
BUILDING_CLEARANCE_M = 5.0     # запас от существующей застройки
ROAD_CLEARANCE_M = 6.0         # запас от проезжей части


def scan_sites(layers: dict[str, list[dict]],
               bounds: list[float],
               planner: RoutePlanner,
               network_coords: list[list[float]],
               size: float = 40.0,
               floors: int = 9,
               step: float = 80.0,
               top: int = 5) -> dict[str, Any]:
    """Сканирует квартал сеткой step×step и возвращает топ площадок.

    Для каждой площадки: полигон, длина трассы, смета, Δ-метрики
    живучести сети. Сортировка — по стоимости присоединения.
    """
    network = LineString(network_coords)
    half = size / 2
    margin = half + BUILDING_CLEARANCE_M

    buildings = []
    for f in layers.get("buildings", []):
        try:
            p = Polygon(f["coordinates"])
            if p.is_valid and not p.is_empty:
                buildings.append(prep(p))
        except (TypeError, ValueError):
            continue
    roads = [LineString(f["coordinates"]) for f in layers.get("roads", [])]

    # Сканируем только окрестность теплосети — остальное заведомо далеко.
    nx0, ny0, nx1, ny1 = network.bounds
    minx = max(bounds[0], nx0 - MAX_DIST_TO_NETWORK_M) + half + 5
    miny = max(bounds[1], ny0 - MAX_DIST_TO_NETWORK_M) + half + 5
    maxx = min(bounds[2], nx1 + MAX_DIST_TO_NETWORK_M) - half - 5
    maxy = min(bounds[3], ny1 + MAX_DIST_TO_NETWORK_M) - half - 5

    candidates: list[dict[str, Any]] = []
    scanned = rejected = 0
    y = miny
    while y <= maxy:
        x = minx
        while x <= maxx:
            site = box(x - margin, y - margin, x + margin, y + margin)
            scanned += 1
            if any(b.intersects(site) for b in buildings):
                rejected += 1
                x += step
                continue
            pt = Point(x, y)
            d_net = network.distance(pt)
            if not (MIN_DIST_TO_NETWORK_M <= d_net <= MAX_DIST_TO_NETWORK_M):
                rejected += 1
                x += step
                continue
            road_buf = half + ROAD_CLEARANCE_M
            if any(r.distance(pt) < road_buf for r in roads):
                rejected += 1
                x += step
                continue
            polygon = [
                [x - half, y - half], [x + half, y - half],
                [x + half, y + half], [x - half, y + half],
                [x - half, y - half],
            ]
            try:
                res = planner.plan(network_coords, polygon,
                                   turn_penalty=DEFAULT_TURN_PENALTY,
                                   road_multiplier=DEFAULT_ROAD_MULTIPLIER)
            except ValueError:
                rejected += 1
                x += step
                continue
            variant = next((v for v in res["variants"]
                            if v["key"] == "balanced"), res["variants"][0])
            est = validate_path(variant["path"], layers)
            if est["collision"]:
                rejected += 1
                x += step
                continue
            imp = network_impact(
                [f["coordinates"] for f in layers.get("heat_networks", [])],
                variant["path"])
            candidates.append({
                "center": [round(x, 1), round(y, 1)],
                "polygon": [[round(px, 1), round(py, 1)] for px, py in polygon],
                "length_m": est["length_m"],
                "cost_mln_rub": est["cost_mln_rub"],
                "turns": est["turns"],
                "road_crossings": est["road_crossings"],
                "entropy_delta": imp["delta"]["entropy_norm"],
                "path": variant["path"],
            })
            x += step
        y += step

    candidates.sort(key=lambda c: c["cost_mln_rub"])
    for rank, c in enumerate(candidates[:top], 1):
        c["rank"] = rank

    return {
        "scanned": scanned,
        "rejected": rejected,
        "viable": len(candidates),
        "building_size_m": size,
        "floors": floors,
        "top": candidates[:top],
    }
