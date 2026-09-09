// Общие геометрические хелперы карты (плоские координаты [x, y], метры).
// Используются деревьями, демо-сценарием и всеми, кому нужна
// простая 2D-геометрия без тяжёлых библиотек.

// mulberry32 — детерминированный ГПСЧ (лес не «прыгает» между рендерами).
export function mulberry32(seed) {
  return () => {
    seed |= 0; seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// Точка в полигоне (ray casting) — кольцо [[x, y], ...].
export function pointInPolygon(x, y, ring) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i];
    const [xj, yj] = ring[j];
    if ((yi > y) !== (yj > y) &&
        x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) {
      inside = !inside;
    }
  }
  return inside;
}

// Расстояние от точки до полилинии.
export function distToPolyline(x, y, coords) {
  let best = Infinity;
  for (let i = 0; i < coords.length - 1; i++) {
    const [x1, y1] = coords[i];
    const [x2, y2] = coords[i + 1];
    const dx = x2 - x1, dy = y2 - y1;
    const t = Math.max(0, Math.min(1,
      ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy || 1)));
    best = Math.min(best, Math.hypot(x - (x1 + t * dx), y - (y1 + t * dy)));
  }
  return best;
}

// Пересечение отрезков p1p2 и p3p4 (строгое, не по концам).
export function segSegIntersect(p1, p2, p3, p4) {
  const d = (a, b, c) => (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
  const d1 = d(p3, p4, p1);
  const d2 = d(p3, p4, p2);
  const d3 = d(p1, p2, p3);
  const d4 = d(p1, p2, p4);
  return ((d1 > 0) !== (d2 > 0)) && ((d3 > 0) !== (d4 > 0));
}

// Пересекается ли осевой прямоугольник (cx,cy,half) с полигоном.
export function boxIntersectsPolygon(cx, cy, half, ring) {
  const corners = [
    [cx - half, cy - half], [cx + half, cy - half],
    [cx + half, cy + half], [cx - half, cy + half],
  ];
  // угол бокса внутри полигона / вершина полигона внутри бокса / рёбра крестятся
  if (corners.some(([x, y]) => pointInPolygon(x, y, ring))) return true;
  if (ring.some(([x, y]) => Math.abs(x - cx) < half && Math.abs(y - cy) < half)) return true;
  for (let i = 0; i < 4; i++) {
    const a = corners[i], b = corners[(i + 1) % 4];
    for (let j = 0; j < ring.length - 1; j++) {
      if (segSegIntersect(a, b, ring[j], ring[j + 1])) return true;
    }
  }
  return false;
}
