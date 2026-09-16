# Oracle — Python-эталон движка (НЕ входит в поставку)

Эталонная реализация движка трассировки на Python 3.11 (FastAPI, Shapely,
pyproj) — используется как тестовый оракул для численной сверки Java-порта
(`app/src/main/java/ru/heatnet/dit/engine/core/`, паритет стоимости ≤ 0,015 %)
и как источник контрактных проверок §10 (`tests/run_engine_smoke.py` — 54,
`tests/rehearse_extra.py` — 24, `tests/e2e_api.py` — против Java API).

Сервисная поставка — Java 11 in-process, эта папка в `docker-compose.yml`
не участвует (протокол 16.09.2026 п.1).

---

Первоначальное назначение (дни 1–5 спринта): ГИС-парсер, триангуляция
рельефа, расчёт подключения зданий к теплосетям.

## Запуск

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Swagger UI: http://localhost:8000/docs

## Endpoints

| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/api/health` | Проверка живости (День 1) |
| GET | `/api/map/layers` | Слои карты: здания, дороги, теплосети (День 2) |
| GET | `/api/terrain/mesh` | Low-poly меш рельефа, триангуляция Делоне (День 3) |
| POST | `/api/terrain/triangulate` | Триангуляция произвольных точек (День 3) |
| POST | `/api/project/connect` | Расчёт врезки здания в теплосеть (День 5) |

## Свои данные

Положите свои GeoJSON в `app/data/`: `buildings.geojson`
(полигоны, атрибут `floors`), `roads.geojson` (линии),
`heat_networks.geojson` (линии). Система координат и прочие
настройки — в `app/config.py` или через переменные окружения.
Для .osm-файлов см. `app/gis/osm_loader.py`.

Подробности по файлам — в `../docs/`.
