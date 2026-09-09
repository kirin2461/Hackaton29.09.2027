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
