# Frontend (React + Three.js)

3D-визуализация карты: low-poly рельеф, здания с extrusion по этажности,
дороги, теплосети, интерфейс «Точка посадки» (Точки А и Б).

## Запуск

```bash
npm install
npm run dev        # http://localhost:5173
```

Бэкенд должен быть запущен на порту 8000 (Vite проксирует `/api/*`).

## Сборка

```bash
npm run build      # продакшн-бандл в dist/
npm run preview    # локальный просмотр сборки
```

## Структура

- `src/App.jsx` — состояние приложения и связка панели со сценой;
- `src/api/client.js` — запросы к FastAPI;
- `src/scene/MapScene.jsx` — Three.js сцена, камера, свет, клики;
- `src/scene/terrain.js` — low-poly рельеф из меша бэкенда;
- `src/scene/buildings.js` — extrusion зданий по этажности;
- `src/scene/networks.js` — дороги, теплосети, линия врезки;
- `src/components/Toolbar.jsx` — панель инструментов.

Подробности по файлам — в `../docs/`.
