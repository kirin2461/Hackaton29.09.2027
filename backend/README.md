# Backend (FastAPI)

Серверная часть хакатон-проекта: ГИС-парсер, триангуляция рельефа,
расчёт подключения зданий к теплосетям.

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
