// Процедурные деревья: оживляют пустыри между зданиями.
// Позиции — детерминированный random (seed), точки внутри зданий
// и ближе 7 м к дорогам/теплосетям отбрасываются.
// Рисуем двумя InstancedMesh (стволы + кроны) — сотни деревьев = 2 draw call.

import * as THREE from 'three';
import { mulberry32, pointInPolygon, distToPolyline } from './geo.js';

const ROAD_CLEARANCE = 8;   // метров от дороги
const HEAT_CLEARANCE = 5;   // метров от теплосети

/** Рассаживает деревья по карте. bounds: [minx, miny, maxx, maxy]. */
export function buildTrees(layersData, bounds, sampler) {
  const group = new THREE.Group();
  group.name = 'trees';
  if (!bounds) return group;

  const buildings = layersData?.layers?.buildings ?? [];
  const roads = layersData?.layers?.roads ?? [];
  const heats = layersData?.layers?.heat_networks ?? [];

  // Густота леса зависит от площади карты: ~1 дерево на 4500 м².
  const area = (bounds[2] - bounds[0]) * (bounds[3] - bounds[1]);
  const treeCount = Math.max(100, Math.min(600, Math.round(area / 4500)));

  const rng = mulberry32(2027);
  const spots = [];
  let attempts = 0;
  while (spots.length < treeCount && attempts < treeCount * 12) {
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
