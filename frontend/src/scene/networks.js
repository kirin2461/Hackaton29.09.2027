// Линейные слои: дороги и теплосети (Дни 2 и 4).
// Линии кладём чуть выше рельефа, чтобы не «проваливались» в меш.

import * as THREE from 'three';
import { mapToScene } from './terrain';

const ROAD_COLOR = 0x636e72; // дороги — серые
const HEAT_COLOR = 0xd63031; // теплосети — красные
const HEAT_SELECTED = 0xfdcb6e; // выбранная теплосеть — жёлтая
const LINE_LIFT = 1.5; // подъём над землёй, метров

function makeLine(points, color, name, userData) {
  const geometry = new THREE.BufferGeometry().setFromPoints(points);
  const material = new THREE.LineBasicMaterial({ color });
  const line = new THREE.Line(geometry, material);
  line.name = name;
  line.userData = userData;
  return line;
}

// Высота линии над землёй в конкретной точке карты: рельеф + подъём.
function scenePoint(sampler, x, y, lift = LINE_LIFT) {
  const ground = sampler ? sampler(x, y) : 0;
  return mapToScene(x, y, ground + lift);
}

/** Все дороги одной группой. sampler — функция высоты рельефа. */
export function buildRoads(features, sampler) {
  const group = new THREE.Group();
  group.name = 'roads';
  for (const f of features) {
    const pts = f.coordinates.map(([x, y]) => scenePoint(sampler, x, y));
    group.add(makeLine(pts, ROAD_COLOR, `road:${f.id}`, { type: 'road', id: f.id }));
  }
  return group;
}

/**
 * Все теплосети одной группой.
 * Вокруг каждой линии строим невидимый «толстый» TubeGeometry —
 * по нему удобно попадать кликом (Line для Raycaster слишком тонкая).
 */
export function buildHeatNetworks(features, sampler, lift = LINE_LIFT) {
  const group = new THREE.Group();
  group.name = 'heat_networks';
  for (const f of features) {
    const pts = f.coordinates.map(([x, y]) => scenePoint(sampler, x, y, lift));
    const line = makeLine(pts, HEAT_COLOR, `heat:${f.id}`, { type: 'heat', id: f.id });
    group.add(line);

    const curve = new THREE.CatmullRomCurve3(pts);
    const tube = new THREE.Mesh(
      new THREE.TubeGeometry(curve, 32, 4, 6, false),
      new THREE.MeshBasicMaterial({ visible: false }),
    );
    tube.name = `heat-hit:${f.id}`;
    tube.userData = { type: 'heat', id: f.id };
    group.add(tube);
  }
  return group;
}

/** Подсветка выбранной теплосети (Точка А). */
export function highlightHeat(group, selectedId) {
  for (const child of group.children) {
    if (child.type !== 'Line') continue;
    const isSel = child.userData.id === selectedId;
    child.material.color.set(isSel ? HEAT_SELECTED : HEAT_COLOR);
  }
}

/** Пунктирная линия врезки от нового здания до теплосети (ответ бэкенда). */
export function buildConnectionLine(connection, sampler, lift = LINE_LIFT) {
  const [fx, fy] = connection.from_point;
  const [tx, ty] = connection.to_point;
  const pts = [scenePoint(sampler, fx, fy, lift + 1), scenePoint(sampler, tx, ty, lift + 1)];
  const geometry = new THREE.BufferGeometry().setFromPoints(pts);
  const line = new THREE.Line(
    geometry,
    new THREE.LineDashedMaterial({ color: 0xfdcb6e, dashSize: 6, gapSize: 4 }),
  );
  line.computeLineDistances(); // обязательно для пунктира
  line.name = 'connection';
  return line;
}
