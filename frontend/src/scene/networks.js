// Линейные слои: дороги и теплосети (Дни 2 и 4).
// Апгрейд графики: дороги — плоские асфальтовые ленты с осевой
// разметкой, теплосети — красные трубы, лежащие на рельефе.

import * as THREE from 'three';
import { mapToScene } from './terrain';

const HEAT_COLOR = 0xd63031; // теплосети — красные
const HEAT_SELECTED = 0xfdcb6e; // выбранная теплосеть — жёлтая
const ROAD_WIDTH = 8; // ширина проезжей части, метров
const ROAD_LIFT = 0.5; // подъём ленты дороги над землёй
const PIPE_LIFT = 1.4; // подъём трубы теплосети над землёй

// Высота точки над землёй: рельеф + подъём.
function scenePoint(sampler, x, y, lift) {
  const ground = sampler ? sampler(x, y) : 0;
  return mapToScene(x, y, ground + lift);
}

// ---------- дороги: асфальтовая лента ----------

/** Лента постоянной ширины вдоль полилинии (triangle strip). */
function buildRibbon(coords, sampler, width, lift) {
  const pts = coords.map(([x, y]) => [x, y]);
  if (pts.length < 2) return null;
  const positions = [];
  const indices = [];
  const half = width / 2;

  for (let i = 0; i < pts.length; i++) {
    const [x, y] = pts[i];
    // направление сегмента (усредняем соседние для гладкости)
    const [px, py] = pts[Math.max(0, i - 1)];
    const [nx, ny] = pts[Math.min(pts.length - 1, i + 1)];
    let dx = nx - px, dy = ny - py;
    const len = Math.hypot(dx, dy) || 1;
    dx /= len; dy /= len;
    // перпендикуляр в плоскости карты
    const ox = -dy * half, oy = dx * half;
    for (const s of [1, -1]) {
      const p = scenePoint(sampler, x + ox * s, y + oy * s, lift);
      positions.push(p.x, p.y, p.z);
    }
    if (i > 0) {
      const a = (i - 1) * 2;
      indices.push(a, a + 1, a + 2, a + 1, a + 3, a + 2);
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geometry.setIndex(indices);
  geometry.computeVertexNormals();
  return geometry;
}

/** Все дороги одной группой: асфальт + жёлтая осевая пунктирная. */
export function buildRoads(features, sampler) {
  const group = new THREE.Group();
  group.name = 'roads';
  const asphalt = new THREE.MeshStandardMaterial({ color: 0x3b4147 });
  const marking = new THREE.LineDashedMaterial({
    color: 0xd8c46a, dashSize: 4, gapSize: 4,
  });
  for (const f of features) {
    const geom = buildRibbon(f.coordinates, sampler, ROAD_WIDTH, ROAD_LIFT);
    if (!geom) continue;
    const mesh = new THREE.Mesh(geom, asphalt);
    mesh.receiveShadow = true;
    mesh.name = `road:${f.id}`;
    mesh.userData = { type: 'road', id: f.id };
    group.add(mesh);

    // осевая разметка
    const pts = f.coordinates.map(([x, y]) => scenePoint(sampler, x, y, ROAD_LIFT + 0.15));
    const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), marking);
    line.computeLineDistances();
    group.add(line);
  }
  return group;
}

// ---------- теплосети: красные трубы ----------

/**
 * Каждая теплосеть — видимая красная труба + невидимая «толстая»
 * труба для попадания кликом (Raycaster по тонкой трубе промахивается).
 */
export function buildHeatNetworks(features, sampler) {
  const group = new THREE.Group();
  group.name = 'heat_networks';
  for (const f of features) {
    const pts = f.coordinates.map(([x, y]) => scenePoint(sampler, x, y, PIPE_LIFT));
    const curve = new THREE.CatmullRomCurve3(pts, false, 'catmullrom', 0.0);

    const pipe = new THREE.Mesh(
      new THREE.TubeGeometry(curve, Math.max(16, pts.length * 6), 1.3, 10, false),
      new THREE.MeshStandardMaterial({ color: HEAT_COLOR }),
    );
    pipe.castShadow = true;
    pipe.name = `heat:${f.id}`;
    pipe.userData = { type: 'heat', id: f.id, baseColor: HEAT_COLOR };
    group.add(pipe);

    const hit = new THREE.Mesh(
      new THREE.TubeGeometry(curve, 32, 4, 6, false),
      new THREE.MeshBasicMaterial({ visible: false }),
    );
    hit.name = `heat-hit:${f.id}`;
    hit.userData = { type: 'heat', id: f.id };
    group.add(hit);
  }
  return group;
}

/** Подсветка выбранной теплосети (Точка А). */
export function highlightHeat(group, selectedId) {
  for (const child of group.children) {
    if (child.userData.type !== 'heat' || !child.material.color) continue;
    if (child.name.startsWith('heat-hit')) continue;
    const isSel = child.userData.id === selectedId;
    child.material.color.set(isSel ? HEAT_SELECTED : child.userData.baseColor);
    child.material.emissive = new THREE.Color(isSel ? HEAT_SELECTED : 0x000000);
    child.material.emissiveIntensity = isSel ? 0.5 : 0;
  }
}

/** Пунктирная линия врезки от нового здания до теплосети (ответ бэкенда). */
export function buildConnectionLine(connection, sampler, lift = PIPE_LIFT) {
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
