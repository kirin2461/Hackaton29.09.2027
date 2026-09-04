"""Загрузчик данных OpenStreetMap (День 2).

GeoPandas умеет читать .osm (XML) напрямую через движок pyogrio —
файл при этом многослойный (points, lines, multilinestrings,
multipolygons). Этот модуль читает OSM-файл и раскладывает объекты
по нашим трём слоям на основе OSM-тегов:

  - buildings     <- любые объекты с тегом building=*
                     (этажность берём из building:levels, иначе 1);
  - roads         <- highway=*;
  - heat_networks <- теги heat=* / pipeline=* / substance=heat —
                     в «сыром» OSM теплосети встречаются редко, поэтому
                     для демо обычно используют подготовленный GeoJSON.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd

from ..config import SOURCE_CRS, TARGET_CRS


def _read_osm(path: Path) -> gpd.GeoDataFrame:
    """Читает все векторные слои OSM-файла в один GeoDataFrame."""
    frames = []
    for osm_layer in ("points", "lines", "multilinestrings", "multipolygons"):
        try:
            frames.append(gpd.read_file(path, layer=osm_layer, engine="pyogrio"))
        except Exception:
            continue  # слоя может не быть в конкретном файле — это нормально
    if not frames:
        return gpd.GeoDataFrame(geometry=[], crs=SOURCE_CRS)
    gdf = gpd.GeoDataFrame(
        gpd.pd.concat(frames, ignore_index=True), crs=frames[0].crs
    )
    if gdf.crs is None:
        gdf = gdf.set_crs(SOURCE_CRS)
    return gdf.to_crs(TARGET_CRS)


def _tags(row) -> dict:
    """Собирает теги объекта: pyogrio складывает прочие теги в колонку
    `other_tags` строкой вида "key"=>"value", разбираем её в словарь."""
    tags = {}
    raw = row.get("other_tags")
    if isinstance(raw, str):
        for pair in raw.split(","):
            if "=>" in pair:
                k, v = pair.split("=>", 1)
                tags[k.strip().strip('"')] = v.strip().strip('"')
    for col in row.index:  # частые теги pyogrio выносит в отдельные колонки
        if col in ("geometry", "other_tags"):
            continue
        val = row[col]
        if isinstance(val, str) and val:
            tags[col] = val
    return tags


def osm_to_layers(path: Path) -> dict[str, gpd.GeoDataFrame]:
    """Разделяет OSM-файл на слои buildings / roads / heat_networks."""
    gdf = _read_osm(Path(path))
    result: dict[str, list[dict]] = {
        "buildings": [], "roads": [], "heat_networks": []
    }
    for _, row in gdf.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        tags = _tags(row)
        props = {"id": str(row.get("osm_id", "")), "name": tags.get("name", "")}
        if "building" in tags and geom.geom_type in ("Polygon", "MultiPolygon"):
            try:
                props["floors"] = int(float(tags.get("building:levels", 1)))
            except ValueError:
                props["floors"] = 1
            result["buildings"].append({"geometry": geom, **props})
        elif "highway" in tags:
            props["highway"] = tags["highway"]
            result["roads"].append({"geometry": geom, **props})
        elif tags.get("substance") == "heat" or "heat" in tags or "pipeline" in tags:
            props["diameter_mm"] = tags.get("diameter", "")
            result["heat_networks"].append({"geometry": geom, **props})
    return {
        layer: gpd.GeoDataFrame(items, geometry="geometry", crs=TARGET_CRS)
        for layer, items in result.items()
    }
