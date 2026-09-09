// Тонкий API-клиент фронтенда (День 1 — связка с FastAPI).
// Все запросы идут на /api/* — в dev-режиме Vite проксирует их
// на http://localhost:8000 (см. vite.config.js).

async function request(path, options) {
  const res = await fetch(path, options);
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body.detail) detail = body.detail;
    } catch { /* тело не JSON — оставляем статус */ }
    throw new Error(detail);
  }
  return res.json();
}

/** Проверка живости бэкенда. */
export const fetchHealth = () => request('/api/health');

/** Метрики живучести существующей теплосети (энтропия, Фидлер, кольца). */
export const fetchNetworkStats = () => request('/api/map/network/stats');

/** Слои карты: здания, дороги, теплосети (День 2). */
export const fetchLayers = () => request('/api/map/layers');

/** Low-poly сетка рельефа: vertices + faces (День 3). */
export const fetchTerrainMesh = () => request('/api/terrain/mesh');

/**
 * Расчёт подключения (День 5):
 * @param {number[][]} polygon контур нового здания (Точка Б)
 * @param {number} floors этажность
 * @param {string} networkId id выбранной теплосети (Точка А)
 */
export const postConnect = (polygon, floors, networkId) =>
  request('/api/project/connect', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      building: { polygon, floors, name: 'Новое здание' },
      network_id: networkId,
    }),
  });

/**
 * Автотрассировка A* (Спринт 2, дни 6–10):
 * три варианта маршрута от теплосети (Точка А) до здания (Точка Б).
 * @param {number[][]} polygon контур нового здания
 * @param {number} floors этажность
 * @param {string} networkId id теплосети
 * @param {number} turnPenalty штраф за поворот 45° (бегунок, усл. метры)
 * @param {number} roadMultiplier множитель стоимости пути по дороге (бегунок)
 */
export const postRoute = (polygon, floors, networkId, turnPenalty, roadMultiplier) =>
  request('/api/route/compute', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      building: { polygon, floors, name: 'Новое здание' },
      network_id: networkId,
      turn_penalty: turnPenalty,
      road_multiplier: roadMultiplier,
    }),
  });

/**
 * Реактивная валидация трассы (День 12): коллизии, переходы, смета.
 * Вызывается после A* и после каждого перетаскивания узла трубы.
 * @param {number[][]} path точки трассы [[x, y], ...]
 */
export const postValidate = (path) =>
  request('/api/route/validate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path }),
  });

/**
 * Сохранение проекта (День 14-15). Бэкенд вернёт 409,
 * если трасса пересекает здание.
 */
export const postSave = (polygon, floors, networkId, path, variant) =>
  request('/api/project/save', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      building: { polygon, floors, name: 'Новое здание' },
      network_id: networkId,
      path,
      variant,
    }),
  });

/**
 * Обратная задача (сканирование площадок): топ-N свободных участков
 * квартала, ранжированных по стоимости технологического присоединения.
 */
export const postScan = (networkId, buildingSize, floors, step = 80, top = 5) =>
  request('/api/route/scan', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      network_id: networkId,
      building_size: buildingSize,
      floors,
      step,
      top,
    }),
  });

/** Список готовых пресетов районов Москвы. */
export const fetchPresets = () => request('/api/map/presets');

/**
 * Загрузка произвольного района из OpenStreetMap (по пресету или bbox).
 * Сервер сам ходит в Overpass API, пересобирает слои и сбрасывает кэш.
 */
export const postLoadBbox = (payload) =>
  request('/api/map/load_bbox', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });

/** Статус лидарного рельефа (активен ли, сколько точек). */
export const fetchLidarStatus = () => request('/api/terrain/lidar/status');

/** Встроенный демо-лидар (Autzen Stadium, USGS 3DEP). */
export const postLidarDemo = () =>
  request('/api/terrain/lidar/demo', { method: 'POST' });

/** Возврат к процедурному рельефу. */
export const postLidarClear = () =>
  request('/api/terrain/lidar/clear', { method: 'POST' });

/** Загрузка своего LAS/LAZ файла (multipart). */
export const postLidarUpload = (file) => {
  const form = new FormData();
  form.append('file', file);
  return request('/api/terrain/lidar/upload', { method: 'POST', body: form });
};

/**
 * Парето-анализ: сканирует пространство весов A* и возвращает
 * все различные трассы с меткой is_pareto (недоминируемые).
 */
export const postPareto = (polygon, floors, networkId) =>
  request('/api/route/pareto', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      building: { polygon, floors, name: 'Новое здание' },
      network_id: networkId,
    }),
  });

/** PDF-отчёт по текущему проекту — скачивается как файл. */
export const postReportPdf = async (polygon, floors, networkId, path, variant) => {
  const res = await fetch('/api/report/pdf', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      building: { polygon, floors, name: 'Новое здание' },
      network_id: networkId,
      path,
      variant,
    }),
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try { detail = (await res.json()).detail ?? detail; } catch { /* ignore */ }
    throw new Error(detail);
  }
  return res.blob();
};
