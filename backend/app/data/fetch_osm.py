"""Загрузка реальных геоданных из OpenStreetMap (через Overpass API).

Тянет здания, дороги и тепловые трубопроводы (man_made=pipeline,
substance=heat/hot_water) для заданного прямоугольника и раскладывает
их по трём GeoJSON-слоям сервиса: buildings / roads / heat_networks.

Запуск (из папки backend):

    python -m app.data.fetch_osm 55.8826 37.4920 55.8943 37.5129

где аргументы — bbox в градусах WGS84: min_lat min_lon max_lat max_lon.
Текущие слои сервиса получены именно так — район Западное Дегунино,
Москва (Бусиновский проезд / Ижорская улица / Коровинское шоссе),
там в OSM размечена реальная теплотрасса от котельной.

Ограничения (хакатон-допущения):
  - учитываются только way-объекты (relations-мультиполигоны пропускаем);
  - этажность: building:levels, иначе эвристика по тегу building=*;
  - геометрии режутся по bbox (Overpass возвращает way целиком).
"""

from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

from shapely.geometry import box as shapely_box
from shapely.geometry import shape

DATA_DIR = Path(__file__).resolve().parent
OVERPASS = "https://overpass-api.de/api/interpreter"

QUERY = """[out:json][timeout:180];(
  way["building"]({bbox});
  way["highway"]({bbox});
  way["man_made"="pipeline"]["substance"~"heat|hot_water"]({bbox});
);out geom;"""

ROAD_KEEP = {"motorway", "trunk", "primary", "secondary", "tertiary",
             "unclassified", "residential", "living_street", "service"}

FLOORS_BY_TYPE = {"apartments": 5, "residential": 3, "house": 2, "detached": 2,
                  "garage": 1, "garages": 1, "shed": 1, "industrial": 2,
                  "commercial": 3, "office": 4, "school": 3, "kindergarten": 2}


def fetch(bbox: str) -> list[dict]:
    """Выполняет Overpass-запрос и возвращает список элементов OSM."""
    data = urllib.parse.urlencode({"data": QUERY.format(bbox=bbox)}).encode()
    # Overpass режет анонимный urllib-агент (406), представляемся явно.
    req = urllib.request.Request(OVERPASS, data=data, headers={
        "User-Agent": "Hackaton29-HeatNetworks/1.0 "
                      "(Moscow DIT hackathon, educational GIS service)",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=240) as r:
        return json.loads(r.read())["elements"]


def way_coords(e: dict) -> list[list[float]]:
    return [[p["lon"], p["lat"]] for p in e["geometry"]]


def clip_geom(feat: dict, clip, want: str):
    """Режет геометрию фичи по bbox, возвращает shapely-геометрию или None."""
    g = shape(feat["geometry"]).intersection(clip)
    if g.is_empty:
        return None
    if g.geom_type != want:
        parts = [x for x in getattr(g, "geoms", []) if x.geom_type == want]
        if not parts:
            return None
        g = max(parts, key=lambda x: x.length if want == "LineString" else x.area)
    return g


def rounded(coords, nd=7):
    return [[round(x, nd), round(y, nd)] for x, y in coords]


def build_buildings(elements, clip) -> list[dict]:
    feats, seen = [], set()
    for e in elements:
        t = e.get("tags", {})
        if "building" not in t or e["type"] != "way":
            continue
        coords = way_coords(e)
        if len(coords) < 3:
            continue
        if coords[0] != coords[-1]:
            coords.append(coords[0])
        if len(set(map(tuple, coords))) < 3:
            continue
        try:
            floors = int(float(t.get("building:levels", "")))
        except ValueError:
            floors = FLOORS_BY_TYPE.get(t.get("building", "yes"), 3)
        addr = t.get("addr:street", "")
        if t.get("addr:housenumber"):
            addr += " " + t["addr:housenumber"]
        feat = {"type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [coords]},
                "properties": {"id": f"b{e['id']}", "floors": floors,
                               "name": t.get("name", ""),
                               "osm_building": t.get("building", "yes"),
                               "addr": addr}}
        g = shape(feat["geometry"])
        if not g.is_valid:
            g = g.buffer(0)
        if g.is_empty or g.area < 1e-9:
            continue
        if g.geom_type == "MultiPolygon":
            g = max(g.geoms, key=lambda p: p.area)
        feat["geometry"] = {"type": "Polygon",
                            "coordinates": [rounded(g.exterior.coords)]}
        h = hash(tuple(map(tuple, feat["geometry"]["coordinates"][0])))
        if h in seen:
            continue
        seen.add(h)
        g = clip_geom(feat, clip, "Polygon")
        if g is None or g.area < 1e-9:
            continue
        feat["geometry"] = {"type": "Polygon",
                            "coordinates": [rounded(g.exterior.coords)]}
        feats.append(feat)
    return feats


def build_roads(elements, clip=None) -> list[dict]:
    feats = []
    for e in elements:
        t = e.get("tags", {})
        if e["type"] != "way" or t.get("highway") not in ROAD_KEEP:
            continue
        coords = way_coords(e)
        if len(coords) < 2:
            continue
        feat = {"type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": {"id": f"r{e['id']}", "name": t.get("name", ""),
                               "highway": t["highway"]}}
        if clip is not None:
            g = clip_geom(feat, clip, "LineString")
            if g is None or g.length < 1e-5:
                continue
            feat["geometry"] = {"type": "LineString",
                                "coordinates": rounded(g.coords)}
        feats.append(feat)
    return feats


def _node_key(pt):
    return (round(pt[0], 6), round(pt[1], 6))


def merge_segments(segs: list[list]) -> list[list]:
    """Жадно склеивает сегменты с общими концами в цепочки."""
    chains = [[*segs[0]]]
    rest = [list(c) for c in segs[1:]]
    while rest:
        progressed = False
        for c in list(rest):
            for ch in chains:
                if _node_key(ch[-1]) == _node_key(c[0]):
                    ch.extend(c[1:])
                elif _node_key(ch[-1]) == _node_key(c[-1]):
                    ch.extend(reversed(c[:-1]))
                elif _node_key(ch[0]) == _node_key(c[-1]):
                    ch[:0] = c[:-1]
                elif _node_key(ch[0]) == _node_key(c[0]):
                    ch[:0] = c[:0:-1]
                else:
                    continue
                rest.remove(c)
                progressed = True
                break
            if not progressed:
                break
        if not progressed:
            chains.append([*rest.pop(0)])
    return sorted(chains, key=len, reverse=True)


def build_heat(elements, clip) -> list[dict]:
    pipes, seen = [], set()
    for e in elements:
        t = e.get("tags", {})
        if e["type"] != "way" or t.get("man_made") != "pipeline":
            continue
        coords = way_coords(e)
        if len(coords) < 2:
            continue
        h = hash(tuple(map(tuple, coords)))
        if h in seen:
            continue
        seen.add(h)
        pipes.append(coords)
    if not pipes:
        return []

    # union-find сегментов по общим узлам — одна связная сеть = один id
    parent = list(range(len(pipes)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    node2segs = defaultdict(list)
    for i, coords in enumerate(pipes):
        for pt in coords:
            node2segs[_node_key(pt)].append(i)
    for segs in node2segs.values():
        for s in segs[1:]:
            parent[find(segs[0])] = find(s)

    groups = defaultdict(list)
    for i in range(len(pipes)):
        groups[find(i)].append(i)

    feats, n = [], 0
    for idxs in sorted(groups.values(),
                       key=lambda g: -sum(len(pipes[i]) for i in g)):
        for chain in merge_segments([pipes[i] for i in idxs]):
            if len(chain) < 2:
                continue
            feat = {"type": "Feature",
                    "geometry": {"type": "LineString", "coordinates": chain},
                    "properties": {"id": "", "name": "",
                                   "source": "OSM man_made=pipeline"}}
            g = clip_geom(feat, clip, "LineString")
            if g is None or g.length < 1e-5:
                continue
            n += 1
            feat["geometry"] = {"type": "LineString",
                                "coordinates": rounded(g.coords)}
            feat["properties"]["id"] = f"h{n}"
            feat["properties"]["name"] = f"Теплотрасса h{n}"
            feats.append(feat)
    return feats


def derive_heat_from_roads(roads: list[dict],
                           clip=None) -> list[dict]:
    """Резервная модель теплосети для районов без OSM-трубопроводов.

    По Москве надземные теплотрассы размечены в OSM местами (обычно
    от крупных котельных). Если в bbox их нет, строим модельную сеть
    вдоль главных магистралей — по СП 124.13330 распределительные
    тепловые сети прокладывают именно вдоль дорог. Берём две самые
    длинные дороги класса primary/secondary/tertiary.
    """
    cand = [f for f in roads
            if f["properties"].get("highway")
            in {"primary", "secondary", "tertiary", "trunk"}]
    cand.sort(key=lambda f: -len(f["geometry"]["coordinates"]))
    feats = []
    for n, f in enumerate(cand[:2], 1):
        g = shape(f["geometry"])
        if clip is not None:
            g = g.intersection(clip)
            if g.is_empty:
                continue
            if g.geom_type != "LineString":
                parts = [x for x in getattr(g, "geoms", [])
                         if x.geom_type == "LineString"]
                if not parts:
                    continue
                g = max(parts, key=lambda x: x.length)
        feats.append({"type": "Feature",
                      "geometry": {"type": "LineString",
                                   "coordinates": rounded(g.coords)},
                      "properties": {
                          "id": f"h{n}",
                          "name": f"Модельная теплотрасса h{n} "
                                  f"(вдоль {f['properties'].get('name') or 'магистрали'})",
                          "source": "derived: along main road "
                                    "(OSM pipelines absent)"}})
    return feats


def run_district(min_lat: float, min_lon: float,
                 max_lat: float, max_lon: float) -> dict:
    """Полный цикл для произвольного bbox: Overpass → 3 слоя GeoJSON.

    Возвращает статистику (для API /api/map/load_bbox). Если в районе
    нет размеченных теплотрасс — подставляет модельную сеть вдоль
    главных дорог (с пометкой source=derived в свойствах).
    """
    bbox = f"{min_lat},{min_lon},{max_lat},{max_lon}"
    clip = shapely_box(min_lon, min_lat, max_lon, max_lat)
    elements = fetch(bbox)

    buildings = build_buildings(elements, clip)
    roads = build_roads(elements, clip)
    heat = build_heat(elements, clip)
    heat_source = "osm"
    if not heat:
        heat = derive_heat_from_roads(roads)
        heat_source = "derived"

    layers = {"buildings": buildings, "roads": roads, "heat_networks": heat}
    for name, feats in layers.items():
        (DATA_DIR / f"{name}.geojson").write_text(json.dumps(
            {"type": "FeatureCollection", "features": feats},
            ensure_ascii=False), encoding="utf-8")

    return {"buildings": len(buildings), "roads": len(roads),
            "heat_networks": len(heat), "heat_source": heat_source,
            "osm_elements": len(elements)}


def main() -> None:
    if len(sys.argv) != 5:
        sys.exit("Использование: python -m app.data.fetch_osm "
                 "min_lat min_lon max_lat max_lon")
    min_lat, min_lon, max_lat, max_lon = map(float, sys.argv[1:5])
    bbox = f"{min_lat},{min_lon},{max_lat},{max_lon}"
    clip = shapely_box(min_lon, min_lat, max_lon, max_lat)

    print(f"Overpass: bbox {bbox} ...")
    elements = fetch(bbox)
    print(f"элементов OSM: {len(elements)}")

    layers = {
        "buildings": build_buildings(elements, clip),
        "roads": build_roads(elements, clip),
        "heat_networks": build_heat(elements, clip),
    }
    for name, feats in layers.items():
        path = DATA_DIR / f"{name}.geojson"
        path.write_text(json.dumps(
            {"type": "FeatureCollection", "features": feats},
            ensure_ascii=False), encoding="utf-8")
        print(f"{path.name}: {len(feats)} объектов")


if __name__ == "__main__":
    main()
