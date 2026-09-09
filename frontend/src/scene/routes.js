// Отрисовка вариантов трассы A* в 3D-сцене (День 8).
// Каждый вариант — труба (TubeGeometry), лежащая на рельефе.
// Выбранный вариант толще и ярче, остальные — полупрозрачные.

import * as THREE from 'three';
import { mapToScene } from './terrain';

const PIPE_LIFT = 1.2; // подъём трубы над землёй, метров
const RADIUS_SELECTED = 2.4;
const RADIUS_IDLE = 1.4;

/** Один вариант трассы -> THREE.Mesh трубы. */
function buildPipe(variant, selected, sampler) {
  const pts = variant.path.map(([x, y]) => {
    const ground = sampler ? sampler(x, y) : 0;
    return mapToScene(x, y, ground + PIPE_LIFT);
  });
  if (pts.length < 2) return null;

  const curve = new THREE.CatmullRomCurve3(pts, false, 'catmullrom', 0.0);
  const geometry = new THREE.TubeGeometry(
    curve,
    Math.max(16, pts.length * 4),
    selected ? RADIUS_SELECTED : RADIUS_IDLE,
    8,
    false,
  );
  const material = new THREE.MeshStandardMaterial({
    color: new THREE.Color(variant.color || '#00b894'),
    transparent: !selected,
    opacity: selected ? 1.0 : 0.45,
    emissive: selected ? new THREE.Color(variant.color || '#00b894') : new THREE.Color(0x000000),
    emissiveIntensity: selected ? 0.35 : 0,
  });
  const mesh = new THREE.Mesh(geometry, material);
  mesh.name = `route:${variant.key}`;
  mesh.userData = { type: 'route', key: variant.key };
  return mesh;
}

/** Все варианты одной группой `routes`. */
export function buildRoutes(variants, selectedKey, sampler) {
  const group = new THREE.Group();
  group.name = 'routes';
  for (const v of variants) {
    const pipe = buildPipe(v, v.key === selectedKey, sampler);
    if (pipe) group.add(pipe);
  }
  return group;
}
