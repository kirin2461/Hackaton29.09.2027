# День 1 — Настройка окружения и архитектуры

## Цель дня

Развернуть репозиторий и поднять связку **FastAPI (backend) + React/Three.js (frontend)**:
два независимых процесса, общающихся по HTTP.

```
Браузер ──> Vite dev-server :5173 ──/api/* (proxy)──> FastAPI :8000
```

## Файлы дня

### `backend/app/main.py`
Точка входа FastAPI. Создаёт приложение, подключает CORS-middleware
(без него браузер блокирует запросы с порта 5173 на порт 8000) и три
роутера: карта, рельеф, проект. Endpoint `GET /api/health` — простейшая
проверка «жив ли сервер», её фронтенд дёргает при старте и показывает
статус в панели.

### `backend/app/config.py`
Все настройки проекта: пути к данным, системы координат (исходная
EPSG:4326 и рабочая метрическая EPSG:32637), список CORS-origins,
параметры сетки рельефа, высота этажа. Каждое значение переопределяется
переменной окружения — удобно для деплоя.

### `backend/app/deps.py`
DI-зависимости FastAPI. `get_parser()` через `lru_cache` создаёт единый
экземпляр ГИС-парсера на весь процесс: GeoJSON-файлы читаются с диска
один раз. Вынесено из `main.py`, чтобы роутеры не импортировали `main`
(иначе циклический импорт).

### `backend/requirements.txt`
Зафиксированные версии Python-зависимостей: FastAPI + uvicorn (сервер),
GeoPandas/Shapely/pyproj (ГИС), SciPy/NumPy (триангуляция).

### `frontend/package.json`
Зависимости фронтенда: React 18, Three.js, Vite + плагин React.
Скрипты: `npm run dev` (разработка), `npm run build` (продакшн-сборка).

### `frontend/vite.config.js`
Конфиг Vite. Ключевое — proxy `/api` → `http://localhost:8000`:
в dev-режиме фронтенд ходит на свой origin, а Vite пересылает запросы
бэкенду. Это решает CORS без единой строчки на клиенте.

### `frontend/index.html`
HTML-оболочка SPA: контейнер `<div id="root">` и подключение
`src/main.jsx`.

### `frontend/src/main.jsx`
Вход React-приложения: монтирует `<App />` в `#root`, подключает стили.

### `frontend/src/App.jsx`
Корневой компонент. В контексте Дня 1 важно: при монтировании он
параллельно запрашивает у бэкенда health-check, слои карты и меш
рельефа — этим проверяется вся связка целиком.

### `frontend/src/api/client.js`
Тонкий HTTP-клиент на `fetch`: функции `fetchHealth`, `fetchLayers`,
`fetchTerrainMesh`, `postConnect`. Единая обработка ошибок: не-OK
статусы превращаются в понятные сообщения из поля `detail` FastAPI.

## Проверка дня

1. `uvicorn app.main:app --reload --port 8000` → `GET /api/health` = `{"status":"ok"}`.
2. `npm run dev` → в панели слева «Backend: подключён».
