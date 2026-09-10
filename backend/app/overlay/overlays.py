"""Внешние источники данных: НСПД, data.mos.ru, произвольный GeoJSON.

Всё «скрещивается» в одну карту: внешний слой приходит в EPSG:4326,
переводится в метрическую CRS сцены (EPSG:32637) и сдвигается на
origin текущей карты — то есть ложится ровно поверх слоёв OSM.

Хранилище — в памяти процесса: слои живут до перезапуска сервиса.
Сырые координаты хранятся в WGS84, поэтому при смене района
(load_bbox) слои можно пересчитать в новую сцену.
"""

from __future__ import annotations

import itertools
from typing import Any

from pyproj import Transformer

_to_metric = Transformer.from_crs("EPSG:4326", "EPSG:32637", always_xy=True)
_to_wgs84 = Transformer.from_crs("EPSG:32637", "EPSG:4326", always_xy=True)

_OVERLAYS: dict[str, dict[str, Any]] = {}
_counter = itertools.count(1)

# Пресеты слоёв НСПД (categoryId в API /api/geoportal/v1/intersects).
NSPD_LAYERS = {
    "nspd_sooruzheniya": {"category": 36383, "title": "НСПД: Сооружения ЕГРН",
                          "color": "#a55eea"},
    "nspd_zdaniya": {"category": 36369, "title": "НСПД: Здания ЕГРН",
                     "color": "#f7b731"},
    "nspd_zouit": {"category": 36940, "title": "НСПД: ЗОУИТ (охранные зоны)",
                   "color": "#eb3b5b"},
    "nspd_redlines": {"category": 38942, "title": "НСПД: Красные линии",
                      "color": "#fc5c65"},
}


def _geom_coords(g: dict[str, Any]) -> Any:
    t = g.get("type")
    c = g.get("coordinates")
    if t in ("Point", "MultiPoint", "LineString", "MultiLineString",
             "Polygon", "MultiPolygon"):
        return t, c
    if t == "GeometryCollection":
        return "GeometryCollection", g.get("geometries", [])
    return None, None


def _map_coords(coords: Any, depth: int = 0):
    """Рекурсивно переводит [lon, lat] → метрические метры (x, y)."""
    if depth == 0:
        lon, lat = coords[0], coords[1]
        x, y = _to_metric.transform(lon, lat)
        return [round(x, 2), round(y, 2)]
    return [_map_coords(c, depth - 1) for c in coords]


_DEPTH = {"Point": 0, "MultiPoint": 1, "LineString": 1,
          "MultiLineString": 2, "Polygon": 2, "MultiPolygon": 3}


def add_overlay(name: str, source: str, color: str,
                geojson: dict[str, Any]) -> dict[str, Any]:
    """Регистрирует слой. Возвращает сводку (id, name, count…)."""
    feats_raw = geojson.get("features") or ([geojson] if geojson.get("type") == "Feature" else [])
    features: list[dict[str, Any]] = []
    for f in feats_raw:
        g = f.get("geometry") or {}
        gtype, coords = _geom_coords(g)
        if gtype is None or not coords:
            continue
        features.append({"geometry_type": gtype, "coordinates": coords,
                         "properties": f.get("properties") or {}})
    if not features:
        raise ValueError("в GeoJSON не найдено ни одной геометрии")
    oid = f"ov{next(_counter)}"
    _OVERLAYS[oid] = {"id": oid, "name": name, "source": source,
                      "color": color, "features": features}
    return {"id": oid, "name": name, "source": source, "color": color,
            "count": len(features)}


def list_overlays_raw() -> list[dict[str, Any]]:
    """Сырые оверлеи в WGS84 (для серверных проверок — например,
    попадания объекта в охранную зону)."""
    return list(_OVERLAYS.values())


def remove_overlay(oid: str) -> bool:
    return _OVERLAYS.pop(oid, None) is not None


def clear_source(source: str) -> None:
    for oid in [k for k, v in _OVERLAYS.items() if v["source"] == source]:
        _OVERLAYS.pop(oid, None)


def list_overlays(origin: tuple[float, float] | None,
                  bounds: list[float] | None) -> list[dict[str, Any]]:
    """Все слои, переведённые в координаты текущей сцены.

    origin — левый нижний угол карты в EPSG:32637 (как в /api/map/layers).
    Слои, полностью выпадающие из охвата карты, отдаются пустыми.
    """
    ox, oy = origin or (0.0, 0.0)
    out = []
    for ov in _OVERLAYS.values():
        feats = []
        for f in ov["features"]:
            gtype, coords = f["geometry_type"], f["coordinates"]
            if gtype == "GeometryCollection":
                continue
            try:
                metric = _map_coords(coords, _DEPTH.get(gtype, 1))
            except (TypeError, ValueError, IndexError):
                continue
            shifted = _shift(metric, ox, oy)
            if bounds and not _touches(shifted, bounds):
                continue
            feats.append({"geometry_type": gtype, "coordinates": shifted,
                          "properties": f["properties"]})
        out.append({"id": ov["id"], "name": ov["name"], "source": ov["source"],
                    "color": ov["color"], "count": len(feats),
                    "features": feats})
    return out


def _shift(coords: Any, ox: float, oy: float) -> Any:
    if isinstance(coords[0], (int, float)):
        return [round(coords[0] - ox, 2), round(coords[1] - oy, 2)]
    return [_shift(c, ox, oy) for c in coords]


def _touches(coords: Any, bounds: list[float]) -> bool:
    """True, если хотя бы одна точка попадает в охват карты (с буфером 200 м)."""
    pad = 200.0
    flat = []

    def walk(c):
        if isinstance(c[0], (int, float)):
            flat.append(c)
        else:
            for cc in c:
                walk(cc)
    walk(coords)
    if not flat:
        return False
    xs = [p[0] for p in flat]
    ys = [p[1] for p in flat]
    return not (max(xs) < bounds[0] - pad or min(xs) > bounds[2] + pad or
                max(ys) < bounds[1] - pad or min(ys) > bounds[3] + pad)


def scene_bounds_wgs84(origin: tuple[float, float],
                       bounds: list[float]) -> dict[str, float]:
    """Охват текущей карты обратно в WGS84 — для запросов в НСПД."""
    ox, oy = origin
    lon1, lat1 = _to_wgs84.transform(ox + bounds[0], oy + bounds[1])
    lon2, lat2 = _to_wgs84.transform(ox + bounds[2], oy + bounds[3])
    return {"min_lon": min(lon1, lon2), "min_lat": min(lat1, lat2),
            "max_lon": max(lon1, lon2), "max_lat": max(lat1, lat2)}
