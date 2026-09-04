# Hackaton29 — ГИС + 3D-визуализация теплосетей

Хакатон-проект: веб-приложение для посадки новых зданий на 3D-карту
и оценки их подключения к существующим теплосетям.

## Стек

| Сторона  | Технологии |
|----------|-----------|
| Backend  | Python 3.11+, FastAPI, GeoPandas, Shapely, SciPy (Delaunay), NumPy |
| Frontend | React 18, Three.js, Vite |

## Структура репозитория

```
├── backend/            # FastAPI-приложение
│   ├── requirements.txt
│   └── app/
│       ├── main.py             # точка входа (День 1)
│       ├── config.py           # настройки (День 1)
│       ├── deps.py             # DI-зависимости FastAPI (День 1)
│       ├── gis/
│       │   ├── parser.py       # ГИС-парсер на GeoPandas (День 2)
│       │   └── osm_loader.py   # загрузчик OSM-файлов (День 2)
│       ├── terrain/
│       │   └── triangulation.py# триангуляция Делоне (День 3)
│       ├── api/
│       │   ├── routes_map.py     # GET /api/map/layers (День 2)
│       │   ├── routes_terrain.py # GET /api/terrain/mesh (День 3)
│       │   └── routes_project.py # POST /api/project/connect (День 5)
│       └── data/               # демо-геоданные (GeoJSON)
│           ├── buildings.geojson
│           ├── roads.geojson
│           └── heat_networks.geojson
├── frontend/           # React + Three.js
│   ├── package.json
│   ├── vite.config.js
│   ├── index.html
│   └── src/
│       ├── main.jsx            # вход React (День 1)
│       ├── App.jsx             # состояние приложения (Дни 1, 5)
│       ├── styles.css
│       ├── api/client.js       # HTTP-клиент к FastAPI (День 1)
│       ├── scene/
│       │   ├── MapScene.jsx    # 3D-сцена Three.js (Дни 4-5)
│       │   ├── terrain.js      # low-poly рельеф из меша (День 4)
│       │   ├── buildings.js    # extrusion зданий (День 4)
│       │   └── networks.js     # дороги и теплосети (Дни 4-5)
│       └── components/
│           └── Toolbar.jsx     # панель «Точка посадки» (День 5)
└── docs/               # подробные пояснения по дням и файлам
    ├── day1-architecture.md
    ├── day2-gis-parser.md
    ├── day3-triangulation.md
    ├── day4-3d-scene.md
    └── day5-landing-point.md
```

Подробное описание каждого файла — в `docs/` (по одному .md на день,
внутри — разбор всех файлов, созданных в этот день).

## Запуск

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

API-документация (Swagger): http://localhost:8000/docs

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Приложение: http://localhost:5173 (запросы `/api/*` проксируются на порт 8000).

## Как пользоваться (День 5)

1. **«+ Здание (Точка Б)»** — выберите этажность и размер, кликните
   по рельефу: появится полупрозрачное зелёное здание.
2. **«⌁ Теплосеть (Точка А)»** — кликните по красной линии теплосети.
3. Бэкенд рассчитает ближайшую точку врезки, длину подключения
   и ориентировочную тепловую нагрузку; пунктирная жёлтая линия
   покажет трассировку на 3D-сцене.

## Статус по плану

- [x] День 1 — FastAPI + React/Three.js, структура репозитория
- [x] День 2 — ГИС-парсер GeoPandas (GeoJSON/OSM), слои: здания/дороги/теплосети
- [x] День 3 — триангуляция Делоне (SciPy), передача треугольников на фронтенд
- [x] День 4 — 3D-окно: low-poly ландшафт + extrusion зданий по этажности
- [x] День 5 — Точка Б (новое здание) и Точка А (выбор теплосети) + расчёт врезки
