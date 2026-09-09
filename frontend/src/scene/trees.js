// Процедурные деревья: оживляют пустыри между зданиями.
// Позиции — детерминированный random (seed), точки внутри зданий
// и ближе 7 м к дорогам/теплосетям отбрасываются.
// Рисуем двумя InstancedMesh (стволы + кроны) — 200 деревьев = 2 draw call.

import * as THREE from 'three';

const TREE_COUNT = 220;
const ROAD_CLEARANCE = 8;   // метров от дороги
const HEAT_CLEARANCE = 5;   // метров от теплосети

// mulberry32 — детерминированный ГПСЧ, чтобы лес не «прыгал» между рендерами.
function mulberry32(seed) {
  return () => {
    seed |= 0; seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// Точка в полигоне (ray casting) — кольцо [[x, y], ...].
function pointInPolygon(x, y, ring) {
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
function distToPolyline(x, y, coords) {
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

/** Рассаживает деревья по карте. bounds: [minx, miny, maxx, maxy]. */
export function buildTrees(layersData, bounds, sampler) {
  const group = new THREE.Group();
  group.name = 'trees';
  if (!bounds) return group;

  const buildings = layersData?.layers?.buildings ?? [];
  const roads = layersData?.layers?.roads ?? [];
  const heats = layersData?.layers?.heat_networks ?? [];

  const rng = mulberry32(2027);
  const spots = [];
  let attempts = 0;
  while (spots.length < TREE_COUNT && attempts < TREE_COUNT * 12) {
    attempts++;
    const x = bounds[0] + rng() * (bounds[2] - bounds[0]);
    const y = bounds[1] + rng() * (bounds[3] - bounds[1]);
    if (buildings.some((b) => pointInPolygon(x, y, b.coordinates))) continue;
    if (roads.some((r) => distToPolyline(x, y, r.coordinates) < ROAD_CLEARANCE)) continue;
    if (heats.some((h) => distToPolyline(x, y, h.coordinates) < HEAT_CLEARANCE)) continue;
    spots.push([x, y, 0.75 + rng() * 0.6]); // масштаб дерева
  }

  const trunkGeom = new THREE.CylinderGeometry(0.35, 0.5, 2.4, 5);
  const crownGeom = new THREE.ConeGeometry(3.1, 8.5, 7);
  const trunkMat = new THREE.MeshStandardMaterial({ color: 0x6d4c2f });
  const crownMat = new THREE.MeshStandardMaterial({
    color: 0x2d6a4f, flatShading: true,
  });

  const trunks = new THREE.InstancedMesh(trunkGeom, trunkMat, spots.length);
  const crowns = new THREE.InstancedMesh(crownGeom, crownMat, spots.length);
  crowns.castShadow = true;

  const m = new THREE.Matrix4();
  const q = new THREE.Quaternion();
  const up = new THREE.Vector3(0, 1, 0);
  spots.forEach(([x, y, s], i) => {
    const ground = sampler ? sampler(x, y) : 0;
    q.setFromAxisAngle(up, x * 13.7 + y * 7.1); // «случайный» поворот
    // ствол: карта (x, y) -> сцена (x, h, -y)
    m.compose(new THREE.Vector3(x, ground + 1.2 * s, -y), q,
      new THREE.Vector3(s, s, s));
    trunks.setMatrixAt(i, m);
    m.compose(new THREE.Vector3(x, ground + (2.4 + 4.2) * s, -y), q,
      new THREE.Vector3(s, s, s));
    crowns.setMatrixAt(i, m);
  });
  trunks.instanceMatrix.needsUpdate = true;
  crowns.instanceMatrix.needsUpdate = true;
  group.add(trunks, crowns);
  return group;
}
