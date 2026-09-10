"""Геодезия: продольный профиль трассы (разрез) и паспорт объекта.

- POST /api/route/profile  — разрез вдоль трубы: рельеф, глубина
  заложения, отметки переходов под дорогами, уклоны.
- POST /api/object/passport — клик по любому зданию карты: его
  характеристики и «коммуникации» — ближайшая теплосеть и точка
  врезки, дороги рядом, охранные зоны (ЗОУИТ из оверлеев НСПД).
"""

from __future__ import annotations

import math
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from shapely.geometry import LineString, Point, Polygon

from ..deps import get_normalized_layers, get_parser
from ..gis.parser import GISParser
from ..overlay import overlays
from ..terrain.heights import get_sampler

router = APIRouter(prefix="/api", tags=["geodesy"])

DEFAULT_DEPTH_M = 3.0  # глубина заложения новой трассы (как в рентген-режиме)


class ProfileIn(BaseModel):
    path: list[list[float]] = Field(min_length=2)
    depth_m: float = Field(default=DEFAULT_DEPTH_M, ge=0.5, le=10.0)
    step_m: float = Field(default=5.0, ge=1.0, le=50.0)


def _map_size(parser: GISParser) -> float:
    raw = parser._bounds()
    if not raw:
        return 1000.0
    size = max(raw[2] - raw[0], raw[3] - raw[1])
    return (size * 1.05) if size > 0 else 1000.0


@router.post("/route/profile")
def route_profile(payload: ProfileIn,
                  parser: GISParser = Depends(get_parser)):
    """Продольный профиль (разрез) трассы.

    Возвращает массив точек: расстояние от начала, отметка земли,
    отметка трубы (земля − глубина), флаги переходов под дорогами.
    """
    path = payload.path
    line = LineString(path)
    length = float(line.length)
    if length <= 0:
        raise HTTPException(422, "Трасса нулевой длины")

    sampler = get_sampler(_map_size(parser))

    # Точки разреза: каждые step_m + обязательно все узлы трассы.
    n = max(int(length / payload.step_m), 8)
    dists = sorted({round(i * length / n, 2) for i in range(n + 1)}
                   | set(_cum_dists(path)))

    layers = get_normalized_layers()
    roads = [LineString(f["coordinates"]) for f in layers.get("roads", [])]

    samples, crossings = [], []
    prev_ground = None
    max_slope = 0.0
    for d in dists:
        pt = line.interpolate(d)
        ground = sampler(pt.x, pt.y)
        if prev_ground is not None and d > prev_ground[0]:
            slope = abs(ground - prev_ground[1]) / (d - prev_ground[0]) * 100
            max_slope = max(max_slope, slope)
        prev_ground = (d, ground)
        # Переход под дорогой: дорога в пределах 4 м от точки профиля.
        on_road = any(r.distance(pt) < 4.0 for r in roads)
        samples.append({"d": round(d, 1), "ground": round(ground, 2),
                        "pipe": round(ground - payload.depth_m, 2),
                        "road": on_road})
    # Сводные переходы: группируем подряд идущие точки on_road.
    run_start = None
    for s in samples + [{"road": False, "d": None}]:
        if s["road"] and run_start is None:
            run_start = s["d"]
        elif not s["road"] and run_start is not None:
            crossings.append({"from_m": run_start, "to_m": s["d"]})
            run_start = None

    return {
        "length_m": round(length, 1),
        "depth_m": payload.depth_m,
        "samples": samples,
        "road_crossings": crossings,
        "max_slope_pct": round(max_slope, 1),
        "elevation_gain_m": round(samples[-1]["ground"] - samples[0]["ground"], 2),
    }


def _cum_dists(path: list[list[float]]) -> list[float]:
    """Накопленные расстояния до каждого узла трассы."""
    out, acc = [0.0], 0.0
    for a, b in zip(path, path[1:]):
        acc += math.hypot(b[0] - a[0], b[1] - a[1])
        out.append(round(acc, 2))
    return out


class ProbeIn(BaseModel):
    x: float
    y: float


@router.post("/terrain/probe")
def terrain_probe(payload: ProbeIn,
                  parser: GISParser = Depends(get_parser)):
    """Геодезический зонд точки: отметка земли, уклон, экспозиция склона.

    Высоты — из той же ЦМР, что отображается в сцене (демо-рельеф
    или лидар). Уклон считается численным градиентом на базе 6 м.
    Это характеристики рельефа («грунт» в терминах модели), а не
    инженерно-геологические изыскания — состав грунта ЦМР не знает.
    """
    from ..terrain import lidar as _lidar
    sampler = get_sampler(_map_size(parser))
    x, y = payload.x, payload.y
    h = 3.0
    z = sampler(x, y)
    zx = (sampler(x + h, y) - sampler(x - h, y)) / (2 * h)
    zy = (sampler(x, y + h) - sampler(x, y - h)) / (2 * h)
    slope = math.hypot(zx, zy) * 100  # %
    # Экспозиция — азимут направления наискорейшего спуска (0 = север).
    aspect = (math.degrees(math.atan2(-zx, zy)) + 360) % 360 if slope > 0.01 else None
    return {
        "x": x, "y": y,
        "ground_z_m": round(z, 2),
        "slope_pct": round(slope, 1),
        "aspect_deg": round(aspect, 0) if aspect is not None else None,
        "source": "lidar" if _lidar.active() else "demo",
    }


@router.get("/map/geo_center")
def map_geo_center(parser: GISParser = Depends(get_parser)):
    """Центр и охват текущего района в WGS84.

    Нужен окну синхронной карты (Яндекс/2ГИС), чтобы открыть виджет
    ровно на той же территории, что загружена в 3D-сцене.
    """
    resp = parser.to_response()
    if not resp.get("bounds"):
        raise HTTPException(503, "Карта не загружена")
    origin = tuple(resp["origin"])
    bbox = overlays.scene_bounds_wgs84(origin, resp["bounds"])
    return {
        "center": [(bbox["min_lon"] + bbox["max_lon"]) / 2,
                   (bbox["min_lat"] + bbox["max_lat"]) / 2],
        "bbox": bbox,
    }


class ToWgs84In(BaseModel):
    x: float
    y: float


@router.post("/map/to_wgs84")
def map_to_wgs84(payload: ToWgs84In, parser: GISParser = Depends(get_parser)):
    """Координаты сцены -> WGS84 (для синхронизации окна карты
    с точкой, куда смотрит 3D-камера)."""
    resp = parser.to_response()
    origin = tuple(resp.get("origin") or (0.0, 0.0))
    lon, lat = overlays._to_wgs84.transform(origin[0] + payload.x,
                                            origin[1] + payload.y)
    return {"lon": lon, "lat": lat}


# ---------- Паспорт объекта ----------

class PassportIn(BaseModel):
    x: float
    y: float


def _nearest_building(layers: dict, x: float, y: float,
                      max_snap_m: float = 15.0):
    """Здание, содержащее точку, или ближайшее в радиусе max_snap_m."""
    pt = Point(x, y)
    best, best_d = None, max_snap_m
    for f in layers.get("buildings", []):
        try:
            poly = Polygon(f["coordinates"])
        except (TypeError, ValueError):
            continue
        if poly.is_empty:
            continue
        d = 0.0 if poly.contains(pt) else poly.distance(pt)
        if d < best_d:
            best, best_d = (f, poly), d
    return best


@router.post("/object/passport")
def object_passport(payload: PassportIn,
                    parser: GISParser = Depends(get_parser)):
    """Паспорт объекта: характеристики здания + его коммуникации."""
    layers = get_normalized_layers()
    found = _nearest_building(layers, payload.x, payload.y)
    if not found:
        raise HTTPException(404, "Рядом с точкой нет зданий "
                            "(кликните ближе к контуру)")
    f, poly = found
    props = f.get("properties") or {}
    floors = props.get("floors", 1)
    area = float(poly.area)
    heat_load = round(area * floors * 0.06, 1)  # как в /api/project/connect

    pt = Point(payload.x, payload.y)
    centroid = poly.centroid

    # Ближайшая теплосеть и точка врезки на ней.
    best_net, best_d, tap = None, None, None
    for net in layers.get("heat_networks", []):
        ln = LineString(net["coordinates"])
        d = float(ln.distance(centroid))
        if best_d is None or d < best_d:
            best_d = d
            best_net = net
            tap = ln.interpolate(ln.project(centroid))

    # Дороги в радиусе 30 м от здания.
    near_roads = []
    for r in layers.get("roads", []):
        ln = LineString(r["coordinates"])
        d = float(ln.distance(poly))
        if d <= 30.0:
            name = (r.get("properties") or {}).get("name") or "без названия"
            near_roads.append({"name": name, "distance_m": round(d, 1)})
    near_roads.sort(key=lambda r: r["distance_m"])

    # Охранные зоны: какие полигоны оверлеев накрывают объект.
    resp = parser.to_response()
    origin = tuple(resp["origin"]) if resp.get("origin") else (0.0, 0.0)
    zones = _overlay_zones(origin, centroid.x, centroid.y)

    # Отметка земли в точке объекта (та же геодезия, что у профиля).
    sampler = get_sampler(_map_size(parser))
    ground = sampler(centroid.x, centroid.y)

    return {
        "id": f["id"],
        "name": props.get("name") or props.get("addr:street") or f["id"],
        "floors": floors,
        "area_m2": round(area, 1),
        "perimeter_m": round(float(poly.length), 1),
        "heat_load_kw": heat_load,
        "ground_z_m": round(ground, 2),
        "centroid": [round(centroid.x, 2), round(centroid.y, 2)],
        "network": ({
            "id": best_net["id"],
            "name": (best_net.get("properties") or {}).get("name") or best_net["id"],
            "distance_m": round(best_d, 1),
            "tap_point": [round(tap.x, 2), round(tap.y, 2)],
        } if best_net else None),
        "roads": near_roads[:5],
        "zones": zones,
    }


def _overlay_zones(origin: tuple[float, float], x: float, y: float,
                   max_zones: int = 5) -> list[str]:
    """Имена оверлеев (ЗОУИТ и др.), чьи полигоны накрывают точку.

    Оверлеи хранятся в WGS84 — точку сцены переводим обратно.
    """
    mx, my = origin[0] + x, origin[1] + y
    lon, lat = overlays._to_wgs84.transform(mx, my)
    pt = Point(lon, lat)
    hits = []
    for ov in overlays.list_overlays_raw():
        for feat in ov["features"]:
            if "Polygon" not in feat.get("geometry_type", ""):
                continue
            if _poly_contains(feat["coordinates"], pt):
                hits.append(ov["name"])
                break
        if len(hits) >= max_zones:
            break
    return hits


def _poly_contains(coords: Any, pt: Point) -> bool:
    """Проверка точки в полигоне (координаты WGS84 оверлея)."""
    polys = coords if coords and isinstance(coords[0][0][0], list) else [coords]
    for rings in polys:
        try:
            if Polygon(rings[0]).contains(pt):
                return True
        except (TypeError, ValueError, IndexError):
            continue
    return False
