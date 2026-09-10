"""Роутер оверлеев: «всё в одну карту».

Эндпоинты:
- GET    /api/overlay/list           — все оверлеи, уже пересчитанные
                                       в координаты текущей сцены;
- POST   /api/overlay/geojson        — добавить оверлей из GeoJSON
                                       (EPSG:4326) — ручная выгрузка
                                       любого источника, включая НСПД;
- DELETE /api/overlay/{id}           — удалить оверлей;
- POST   /api/overlay/nspd           — живой запрос к НСПД (ЕГРН) по
                                       охвату текущей карты;
- POST   /api/overlay/datamos        — живой запрос к data.mos.ru.
"""

import logging
import socket
from urllib.error import HTTPError, URLError

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..deps import get_parser
from ..gis.parser import GISParser
from ..overlay import overlays, sources

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/overlay", tags=["overlay"])

_MAX_FEATURES = 5000  # защита памяти: столько объектов максимум в одном оверлее


class GeoJSONOverlayIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    color: str = Field(default="#8a5cf6", pattern=r"^#[0-9a-fA-F]{6}$")
    source: str = Field(default="geojson", max_length=40)
    geojson: dict


class NspdIn(BaseModel):
    layers: list[str] = Field(min_length=1)


class DataMosIn(BaseModel):
    dataset_id: int
    api_key: str = Field(min_length=1)
    limit: int = Field(default=500, ge=1, le=5000)
    name: str | None = None
    color: str = Field(default="#00b8d4", pattern=r"^#[0-9a-fA-F]{6}$")


def _scene_geometry(parser: GISParser):
    """(origin, bounds) текущей карты — для пересчёта оверлеев."""
    resp = parser.to_response()
    if not resp.get("bounds"):
        raise HTTPException(503, "Карта не загружена — охват неизвестен")
    return resp["origin"], resp["bounds"]


@router.get("/list")
def overlay_list(parser: GISParser = Depends(get_parser)):
    """Все оверлеи в координатах текущей сцены (как /api/map/layers)."""
    origin, bounds = _scene_geometry(parser)
    return {"overlays": overlays.list_overlays(tuple(origin), bounds)}


@router.post("/geojson")
def overlay_add_geojson(payload: GeoJSONOverlayIn):
    """Добавить оверлей из произвольного GeoJSON (EPSG:4326).

    Универсальная точка входа: сюда же загружаются ручные выгрузки
    НСПД (когда геопортал недоступен с сервера из-за Qrator) — результат
    на карте тот же.
    """
    try:
        ov = overlays.add_overlay(payload.name, payload.source,
                                  payload.color, payload.geojson)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"ok": True, "overlay": ov}


@router.delete("/{overlay_id}")
def overlay_delete(overlay_id: str):
    if not overlays.remove_overlay(overlay_id):
        raise HTTPException(404, "Оверлей не найден")
    return {"ok": True}


_NSPD_MANUAL_HINT = (
    "Геопортал НСПД не ответил (защита Qrator обычно блокирует запросы "
    "из дата-центров). Выгрузите слой вручную: откройте nspd.gov.ru с "
    "домашнего IP, включите нужный слой, экспортируйте GeoJSON "
    "(или используйте библиотеку pynspd) и загрузите файл через "
    "POST /api/overlay/geojson — результат на карте будет тот же.")


@router.post("/nspd")
def overlay_add_nspd(payload: NspdIn, parser: GISParser = Depends(get_parser)):
    """Живой запрос к НСПД: пересечение слоёв ЕГРН с охватом карты."""
    unknown = [k for k in payload.layers if k not in overlays.NSPD_LAYERS]
    if unknown:
        raise HTTPException(422, f"Неизвестные слои НСПД: {unknown}")
    origin, bounds = _scene_geometry(parser)
    bbox = overlays.scene_bounds_wgs84(tuple(origin), bounds)
    added, errors = [], {}
    for key in payload.layers:
        spec = overlays.NSPD_LAYERS[key]
        try:
            feats = sources.nspd_intersects(spec["category"], bbox)
            feats = feats[:_MAX_FEATURES]
            overlays.clear_source(key)
            ov = overlays.add_overlay(spec["title"], key, spec["color"],
                                      {"type": "FeatureCollection",
                                       "features": feats})
            added.append(ov)
        except (URLError, HTTPError, TimeoutError, socket.timeout, OSError) as e:
            log.warning("НСПД %s недоступен: %s", key, e)
            errors[key] = str(e)
    if not added:
        raise HTTPException(503, f"{_NSPD_MANUAL_HINT} Детали: {errors}")
    return {"ok": True, "added": added, "errors": errors,
            "hint": _NSPD_MANUAL_HINT if errors else None}


@router.post("/datamos")
def overlay_add_datamos(payload: DataMosIn):
    """Живой запрос к data.mos.ru: точечный набор → оверлей на карте."""
    try:
        feats, rows = sources.datamos_points(
            payload.dataset_id, payload.api_key, payload.limit)
    except HTTPError as e:
        if e.code in (401, 403):
            raise HTTPException(401, "data.mos.ru отклонил api_key. "
                                "Ключ бесплатный: регистрация на data.mos.ru "
                                "→ профиль → «Ключ доступа», ~2 минуты.")
        raise HTTPException(502, f"data.mos.ru: HTTP {e.code}")
    except (URLError, TimeoutError, socket.timeout, OSError) as e:
        raise HTTPException(502, f"data.mos.ru недоступен: {e}")
    if not feats:
        raise HTTPException(404, f"Набор {payload.dataset_id}: {rows} строк, "
                            "но ни в одной не нашлось координат WGS84 "
                            "(поля geoData / Longitude_WGS84 / Latitude_WGS84)")
    feats = feats[:_MAX_FEATURES]
    name = payload.name or f"data.mos.ru: набор {payload.dataset_id}"
    ov = overlays.add_overlay(name, "datamos", payload.color,
                              {"type": "FeatureCollection", "features": feats})
    return {"ok": True, "overlay": ov, "rows_seen": rows}
