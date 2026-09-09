"""Роуты картографических слоёв (День 2)."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..deps import get_normalized_layers, get_parser, get_planner
from ..gis.parser import LAYER_HEAT, GISParser
from ..routing.netstats import network_metrics

router = APIRouter(prefix="/api/map", tags=["map"])


@router.get("/layers")
def get_layers(parser: GISParser = Depends(get_parser)):
    """Все слои карты одним запросом: здания, дороги, теплосети.

    Формат ответа:
      {
        "crs": "EPSG:32637",
        "bounds": [minx, miny, maxx, maxy],
        "layers": {
          "buildings":     [ {id, geometry_type, coordinates, properties}, ... ],
          "roads":         [ ... ],
          "heat_networks": [ ... ]
        }
      }
    """
    return parser.to_response()


@router.get("/network/stats")
def get_network_stats(layers: dict = Depends(get_normalized_layers)):
    """Метрики живучести существующей теплосети (без новых веток).

    Энтропия распределения длин сегментов, цикломатическое число
    (кольцевание), число Фидлера, доля тупиковых узлов — базовая
    линия, с которой сравнивается Δ-импакт нового подключения.
    """
    lines = [f["coordinates"] for f in layers.get(LAYER_HEAT, [])]
    return network_metrics(lines)


# --- Загрузка произвольного района Москвы из OpenStreetMap ---------

# Пресеты для демо: разные районы, чтобы на защите грузить живьём.
MOSCOW_PRESETS: dict[str, tuple[float, float, float, float]] = {
    # min_lat, min_lon, max_lat, max_lon
    "degunino": (55.8826, 37.4920, 55.8943, 37.5129),   # текущий
    "bibirevo": (55.8800, 37.5930, 55.8920, 37.6130),
    "mitino": (55.8380, 37.3530, 55.8500, 37.3730),
    "marino": (55.6440, 37.7350, 55.6560, 37.7550),
    "troparevo": (55.6400, 37.4550, 55.6520, 37.4750),
}


class LoadBboxRequest(BaseModel):
    """Тело POST /api/map/load_bbox: bbox WGS84 или имя пресета."""

    preset: str | None = Field(None, description="Имя пресета района")
    min_lat: float | None = Field(None, ge=-90, le=90)
    min_lon: float | None = Field(None, ge=-180, le=180)
    max_lat: float | None = Field(None, ge=-90, le=90)
    max_lon: float | None = Field(None, ge=-180, le=180)


@router.get("/presets")
def get_presets():
    """Список готовых районов для кнопки «загрузить район»."""
    return {"presets": [
        {"key": k, "bbox": list(v)} for k, v in MOSCOW_PRESETS.items()]}


@router.post("/load_bbox")
def load_bbox(req: LoadBboxRequest):
    """Загружает любой квартал из OSM и пересобирает все слои.

    Сервер сам ходит в Overpass API, режет геометрии по bbox, пишет
    buildings/roads/heat_networks.geojson и сбрасывает кэш парсера,
    планировщика и нормализованных слоёв — следующие запросы уже
    работают с новым районом. Если в районе нет размеченных
    теплотрасс, строится модельная сеть вдоль главных дорог
    (с пометкой source=derived).
    """
    from ..data.fetch_osm import run_district  # тяжёлые импорты — лениво

    if req.preset:
        if req.preset not in MOSCOW_PRESETS:
            raise HTTPException(404, f"Неизвестный пресет '{req.preset}'")
        min_lat, min_lon, max_lat, max_lon = MOSCOW_PRESETS[req.preset]
    elif None not in (req.min_lat, req.min_lon, req.max_lat, req.max_lon):
        min_lat, min_lon = req.min_lat, req.min_lon
        max_lat, max_lon = req.max_lat, req.max_lon
        if min_lat >= max_lat or min_lon >= max_lon:
            raise HTTPException(400, "min должно быть меньше max")
        # Ограничиваем размер (~3×3 км), чтобы Overpass не задумался.
        if (max_lat - min_lat) > 0.03 or (max_lon - min_lon) > 0.05:
            raise HTTPException(400, "Слишком большой bbox (макс ~3 км)")
    else:
        raise HTTPException(400, "Нужен preset или полный bbox")

    try:
        stats = run_district(min_lat, min_lon, max_lat, max_lon)
    except Exception as e:  # Overpass таймауты/5xx — отдаём 502
        raise HTTPException(502, f"Overpass API недоступен: {e}")

    if stats["buildings"] == 0:
        raise HTTPException(422, "В этом bbox нет зданий в OSM")

    # Сбрасываем кэши: новые geojson уже на диске.
    get_parser.cache_clear()
    get_planner.cache_clear()
    get_normalized_layers.cache_clear()

    return {"ok": True,
            "bbox": [min_lat, min_lon, max_lat, max_lon],
            "stats": stats}
