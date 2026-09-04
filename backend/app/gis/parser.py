"""ГИС-парсер на GeoPandas (День 2).

Читает геоданные (GeoJSON или OSM XML) и раскладывает их по
тематическим слоям:
  - buildings      — здания (полигоны, обязателен атрибут floors);
  - roads          — дороги (линии);
  - heat_networks  — существующие теплосети (линии).

Результат работы — «нормализованные» словари, готовые к отдаче
в JSON: координаты переведены в метрическую CRS, чтобы фронтенду
было просто строить 3D-сцену (1 единица = 1 метр).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import geopandas as gpd

from ..config import SOURCE_CRS, TARGET_CRS

# Три тематических слоя карты.
LAYER_BUILDINGS = "buildings"
LAYER_ROADS = "roads"
LAYER_HEAT = "heat_networks"
LAYERS = (LAYER_BUILDINGS, LAYER_ROADS, LAYER_HEAT)


class GISParser:
    """Загружает GeoJSON-файлы слоёв и приводит их к единому виду.

    Ожидаемое соглашение по данным: в папке `data_dir` лежат файлы
    `<layer>.geojson` для каждого слоя из `LAYERS`. Отсутствующий
    файл не считается ошибкой — слой просто будет пустым.
    """

    def __init__(self, data_dir: Path, source_crs: str = SOURCE_CRS,
                 target_crs: str = TARGET_CRS) -> None:
        self.data_dir = Path(data_dir)
        self.source_crs = source_crs
        self.target_crs = target_crs
        self._cache: dict[str, gpd.GeoDataFrame] = {}

    # ---------- чтение ----------

    def load_layer(self, layer: str) -> gpd.GeoDataFrame:
        """Читает один слой с диска и переводит в метрическую CRS."""
        if layer in self._cache:
            return self._cache[layer]
        path = self.data_dir / f"{layer}.geojson"
        if not path.exists():
            gdf = gpd.GeoDataFrame(geometry=[], crs=self.target_crs)
        else:
            gdf = gpd.read_file(path)
            if gdf.crs is None:
                gdf = gdf.set_crs(self.source_crs)
            gdf = gdf.to_crs(self.target_crs)
        self._cache[layer] = gdf
        return gdf

    def load_all(self) -> dict[str, gpd.GeoDataFrame]:
        """Загружает все три слоя одним словарём."""
        return {layer: self.load_layer(layer) for layer in LAYERS}

    # ---------- нормализация для фронтенда ----------

    @staticmethod
    def _geom_coords(geom: Any) -> Any:
        """Возвращает координаты геометрии в простом JSON-виде.

        Полигоны и линии режем до 2D (x, y) — высоту зданиям задаёт
        атрибут floors, а не третья координата.
        """
        if geom is None or geom.is_empty:
            return None
        if geom.geom_type == "Polygon":
            ring = list(geom.exterior.coords)
            return [[round(x, 2), round(y, 2)] for x, y, *_ in ring]
        if geom.geom_type in ("LineString", "LinearRing"):
            return [[round(x, 2), round(y, 2)] for x, y, *_ in geom.coords]
        if geom.geom_type == "Point":
            return [round(geom.x, 2), round(geom.y, 2)]
        # Multi* и прочее — берём первую составляющую, хакатон-допущение.
        parts = getattr(geom, "geoms", None)
        if parts:
            return GISParser._geom_coords(parts[0])
        return None

    def layer_to_features(self, layer: str) -> list[dict]:
        """Превращает GeoDataFrame слоя в список простых feature-словарей."""
        gdf = self.load_layer(layer)
        features: list[dict] = []
        for idx, row in gdf.iterrows():
            coords = self._geom_coords(row.geometry)
            if coords is None:
                continue
            props = {k: v for k, v in row.items() if k != "geometry"}
            # Нормализуем этажность здания — она нужна для extrusion (День 4).
            if layer == LAYER_BUILDINGS:
                try:
                    props["floors"] = max(1, int(props.get("floors", 1)))
                except (TypeError, ValueError):
                    props["floors"] = 1
            features.append({
                "id": str(props.get("id", idx)),
                "geometry_type": row.geometry.geom_type,
                "coordinates": coords,
                "properties": props,
            })
        return features

    @staticmethod
    def _shift(coords: Any, ox: float, oy: float) -> Any:
        """Сдвигает координаты feature на (-ox, -oy) — нормализация
        к локальному началу координат карты."""
        if coords is None:
            return None
        if isinstance(coords[0], (int, float)):  # точка [x, y]
            return [round(coords[0] - ox, 2), round(coords[1] - oy, 2)]
        return [[round(x - ox, 2), round(y - oy, 2)] for x, y in coords]

    def to_response(self) -> dict:
        """Полный ответ для GET /api/map/layers: все слои + охват карты.

        Координаты нормализуются: из всех X и Y вычитается левый нижний
        угол совокупного охвата, поэтому карта начинается от (0, 0)
        и идеально ложится рядом с демо-рельефом (0..TERRAIN_SIZE_M).
        Реальный UTM-угол возвращается в поле origin — по нему всегда
        можно восстановить абсолютные координаты.
        """
        raw_bounds = self._bounds()
        ox, oy = (raw_bounds[0], raw_bounds[1]) if raw_bounds else (0.0, 0.0)
        layers: dict[str, list[dict]] = {}
        for layer in LAYERS:
            feats = self.layer_to_features(layer)
            for f in feats:
                f["coordinates"] = self._shift(f["coordinates"], ox, oy)
            layers[layer] = feats
        bounds = ([0.0, 0.0, round(raw_bounds[2] - ox, 2),
                   round(raw_bounds[3] - oy, 2)] if raw_bounds else None)
        return {
            "crs": self.target_crs,
            "origin": [round(ox, 2), round(oy, 2)],
            "bounds": bounds,
            "layers": layers,
        }

    def _bounds(self) -> list[float] | None:
        """Совокупный охват всех слоёв [minx, miny, maxx, maxy] — нужен
        фронтенду, чтобы отцентрировать камеру над картой."""
        boxes = []
        for layer in LAYERS:
            gdf = self.load_layer(layer)
            if not gdf.empty:
                boxes.append(gdf.total_bounds)
        if not boxes:
            return None
        minx = min(b[0] for b in boxes)
        miny = min(b[1] for b in boxes)
        maxx = max(b[2] for b in boxes)
        maxy = max(b[3] for b in boxes)
        return [round(minx, 2), round(miny, 2), round(maxx, 2), round(maxy, 2)]
