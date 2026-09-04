// «Выдавливание» (extrusion) зданий по этажности (День 4).
// Контур здания (полигон в метрах) превращаем в THREE.Shape
// и вытягиваем вверх на floors * FLOOR_HEIGHT метров.

import * as THREE from 'three';
import { mapToScene } from './terrain';

export const FLOOR_HEIGHT = 3.0; // метров на этаж — как FLOOR_HEIGHT_M на бэкенде

/** Одно здание -> THREE.Mesh с extrusion-геометрией. */
export function buildBuilding(feature) {
  const ring = feature.coordinates; // [[x, y], ...] — внешнее кольцо полигона
  const floors = feature.properties?.floors ?? 1;
  const height = floors * FLOOR_HEIGHT;

  const shape = new THREE.Shape();
  ring.forEach(([x, y], i) => {
    // Shape живёт в плоскости XY Three.js; после поворота меша
    // на -90° вокруг X плоскость XY ляжет на «землю» (XZ).
    if (i === 0) shape.moveTo(x, y);
    else shape.lineTo(x, y);
  });

  const geometry = new THREE.ExtrudeGeometry(shape, {
    depth: height,
    bevelEnabled: false,
  });
  geometry.rotateX(-Math.PI / 2); // выдавливание теперь идёт вверх (ось Y)

  // Цвет по этажности: малоэтажка светлее, высотки темнее.
  const t = Math.min(1, floors / 12);
  const color = new THREE.Color().lerpColors(
    new THREE.Color(0xe8dcc4),
    new THREE.Color(0x8d6e63),
    t,
  );
  const material = new THREE.MeshStandardMaterial({ color, flatShading: true });

  const mesh = new THREE.Mesh(geometry, material);
  mesh.name = `building:${feature.id}`;
  mesh.userData = { type: 'building', id: feature.id, floors };
  return mesh;
}

/** Новое перспективное здание (Точка Б) — полупрозрачное, подсвеченное. */
export function buildNewBuilding(polygon, floors) {
  const feature = {
    id: 'new-building',
    coordinates: polygon,
    properties: { floors },
  };
  const mesh = buildBuilding(feature);
  mesh.material = new THREE.MeshStandardMaterial({
    color: 0x00b894,
    transparent: true,
    opacity: 0.75,
    flatShading: true,
  });
  mesh.name = 'new-building';
  mesh.userData = { type: 'new-building', floors };
  return mesh;
}

/** Маркер точки клика на рельефе — маленькая сфера. */
export function buildMarker(scenePoint, color = 0x00b894) {
  const mesh = new THREE.Mesh(
    new THREE.SphereGeometry(6, 16, 16),
    new THREE.MeshBasicMaterial({ color }),
  );
  mesh.position.copy(scenePoint);
  return mesh;
}

/**
 * «Опускает» здание на рельеф: ставит меш по высоте в центре контура.
 * Без этого здания на холмах оказываются наполовину под землёй.
 */
export function drapeOnTerrain(mesh, sampler, ring) {
  if (!sampler) return;
  let cx = 0;
  let cy = 0;
  for (const [x, y] of ring) { cx += x; cy += y; }
  mesh.position.y = sampler(cx / ring.length, cy / ring.length);
}

export { mapToScene };
