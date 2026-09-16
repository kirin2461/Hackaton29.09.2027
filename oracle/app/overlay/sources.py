"""Коннекторы внешних источников: НСПД и data.mos.ru.

НСПД (nspd.gov.ru) защищён Qrator и не отдаёт данные запросам из
дата-центров — с боевого сервера запрос, скорее всего, не пройдёт.
Поэтому коннектор честно возвращает 503 с инструкцией: выгрузить
слой с домашнего IP (геопортал или pynspd) и загрузить GeoJSON
через POST /api/overlay/geojson — результат тот же.

data.mos.ru доступен с сервера, но требует бесплатный api_key
(регистрация на data.mos.ru занимает ~2 минуты).
"""

from __future__ import annotations

import json
import threading
import urllib.request
import urllib.error
from typing import Any

NSPD_INTERSECTS = "https://nspd.gov.ru/api/geoportal/v1/intersects"
DATAMOS_ROWS = "https://apidata.mos.ru/v1/datasets/{dataset_id}/rows"

UA = "Hackaton29-HeatNetworks/1.0 (Moscow DIT hackathon; heat routing demo)"

_HARD_TIMEOUT = 40  # сек; urllib-таймаут не покрывает зависший DNS/TLS-handshake


def _hard_call(fn, *args):
    """Запускает сетевой вызов с жёстким таймаутом.

    urllib-таймаут не ловит зависший DNS-резолв или TLS-handshake
    (случай Qrator: соединение «висит» молча). Поэтому вызов идёт
    в daemon-потоке: по истечении _HARD_TIMEOUT роутер получает
    TimeoutError, а зависший поток умирает сам при первой записи
    в сокет и не блокирует остановку процесса.
    """
    result, error = [], []

    def run():
        try:
            result.append(fn(*args))
        except Exception as e:  # noqa: BLE001 — прокидываем как есть
            error.append(e)

    th = threading.Thread(target=run, daemon=True)
    th.start()
    th.join(_HARD_TIMEOUT)
    if th.is_alive():
        raise TimeoutError(f"источник не ответил за {_HARD_TIMEOUT} с")
    if error:
        raise error[0]
    return result[0]


def _post_json(url: str, payload: dict, timeout: int = 45) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": UA,
                 "Referer": "https://nspd.gov.ru/map"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def nspd_payload(category_id: int, bbox: dict[str, float]) -> dict:
    """Тело запроса к /api/geoportal/v1/intersects.

    Вынесено отдельно, чтобы браузерный обход Qrator (запрос с домашнего
    IP прямо из вкладки пользователя) использовал ровно тот же формат,
    что и серверный коннектор.
    """
    geom = {
        "type": "Polygon",
        "coordinates": [[
            [bbox["min_lon"], bbox["min_lat"]],
            [bbox["max_lon"], bbox["min_lat"]],
            [bbox["max_lon"], bbox["max_lat"]],
            [bbox["min_lon"], bbox["max_lat"]],
            [bbox["min_lon"], bbox["min_lat"]],
        ]],
        "crs": {"type": "name", "properties": {"name": "EPSG:4326"}},
    }
    return {"categories": [{"id": category_id}],
            "geom": {"type": "FeatureCollection",
                     "features": [{"geometry": geom, "type": "Feature",
                                   "properties": {}}]}}


def nspd_intersects(category_id: int, bbox: dict[str, float]) -> list[dict]:
    """Объекты категории НСПД, пересекающиеся с bbox (WGS84)."""
    data = _hard_call(_post_json, NSPD_INTERSECTS,
                      nspd_payload(category_id, bbox))
    return (data.get("data") or {}).get("features") or []


# Поля, в которых data.mos.ru обычно хранит координаты.
_LON_FIELDS = ("Longitude_WGS84", "longitude", "Longitude", "X_WGS84", "lon")
_LAT_FIELDS = ("Latitude_WGS84", "latitude", "Latitude", "Y_WGS84", "lat")


def _row_point(cells: dict[str, Any]) -> list[float] | None:
    """Извлекает [lon, lat] из строки набора data.mos.ru."""
    geo = cells.get("geoData")
    if isinstance(geo, dict) and geo.get("coordinates"):
        return [geo["coordinates"][0], geo["coordinates"][1]]
    lon = next((cells[k] for k in _LON_FIELDS if cells.get(k) is not None), None)
    lat = next((cells[k] for k in _LAT_FIELDS if cells.get(k) is not None), None)
    if lon is None or lat is None:
        return None
    try:
        return [float(str(lon).replace(",", ".")),
                float(str(lat).replace(",", "."))]
    except ValueError:
        return None


def _datamos_rows(url: str) -> list:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def datamos_points(dataset_id: int, api_key: str,
                   limit: int = 500) -> tuple[list[dict], int]:
    """Точечные объекты набора data.mos.ru → GeoJSON-фичи.

    Возвращает (features, total_rows_seen).
    """
    url = f"{DATAMOS_ROWS.format(dataset_id=dataset_id)}?$top={min(limit, 1000)}&api_key={api_key}"
    rows = _hard_call(_datamos_rows, url)
    features = []
    for row in rows:
        cells = row.get("Cells") or row.get("cells") or {}
        pt = _row_point(cells)
        if pt is None:
            continue
        name = (cells.get("Name") or cells.get("FullName")
                or cells.get("ObjectName") or cells.get("ShortName")
                or cells.get("Address") or f"#{row.get('Number', '?')}")
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": pt},
            "properties": {"name": str(name)[:120]},
        })
    return features, len(rows)
