// «Выдавливание» (extrusion) зданий по этажности (День 4).
// Апгрейд графики: фасады с окнами (процедурная текстура),
// двускатные крыши у малоэтажек, парапеты у высоток,
// индивидуальный оттенок каждого здания, тени.

import * as THREE from 'three';
import { mapToScene } from './terrain';

export const FLOOR_HEIGHT = 3.0; // метров на этаж — как FLOOR_HEIGHT_M на бэкенде

// ---------- процедурная текстура фасада ----------
// Один тайл = окно 3×3 м. UV extrude-геометрии в метрах,
// поэтому repeat = 1/3 даёт окно каждые 3 метра фасада.
let _facadeTexture = null;
function facadeTexture() {
  if (_facadeTexture) return _facadeTexture;
  const c = document.createElement('canvas');
  c.width = c.height = 64;
  const g = c.getContext('2d');
  g.fillStyle = '#f2ede4'; // стена
  g.fillRect(0, 0, 64, 64);
  g.fillStyle = '#2c3e50'; // окно
  g.fillRect(14, 10, 36, 40);
  g.fillStyle = '#7fb2d9'; // стекло
  g.fillRect(17, 13, 30, 34);
  g.fillStyle = 'rgba(255,255,255,0.35)'; // блик
  g.fillRect(17, 13, 10, 34);
  const tex = new THREE.CanvasTexture(c);
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  tex.repeat.set(1 / 3, 1 / 3);
  tex.anisotropy = 4;
  _facadeTexture = tex;
  return tex;
}

// Оттенок здания из его id: палитра реальной застройки
// (панельки, кирпич, штукатурка), но без «ряби».
const PALETTE = [0xe8dcc4, 0xd9b99b, 0xc9a186, 0xe6cfA8, 0xd7ccc8, 0xbcaaa4];
function buildingColor(id, floors) {
  let h = 0;
  for (const ch of String(id)) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  const base = new THREE.Color(PALETTE[h % PALETTE.length]);
  // высотки чуть темнее
  return base.lerp(new THREE.Color(0x8d6e63), Math.min(0.35, floors / 40));
}

/** Двускатная крыша-призма над bbox контура (малоэтажки). */
function buildGableRoof(ring, baseHeight) {
  let minx = 1e9, maxx = -1e9, miny = 1e9, maxy = -1e9;
  for (const [x, y] of ring) {
    minx = Math.min(minx, x); maxx = Math.max(maxx, x);
    miny = Math.min(miny, y); maxy = Math.max(maxy, y);
  }
  const cx = (minx + maxx) / 2, cy = (miny + maxy) / 2;
  const w = maxx - minx, d = maxy - miny;
  const alongX = w >= d;           // конёк вдоль длинной стороны
  const L = (alongX ? w : d) / 2;  // полудлина конька
  const W = (alongX ? d : w) / 2;  // полупролёт
  const H = Math.max(2, Math.min(6, W * 0.45)); // высота конька
  const A = alongX ? [1, 0] : [0, 1]; // ось конька
  const B = [A[1], A[0] ? 0 : 1];   // поперечная ось
  // вершины в КАРТОВЫХ координатах (x, y, высота)
  const corner = (sa, sb, h) => [
    cx + A[0] * L * sa + B[0] * W * sb,
    cy + A[1] * L * sa + B[1] * W * sb,
    baseHeight + h,
  ];
  const c00 = corner(-1, -1, 0), c01 = corner(-1, 1, 0);
  const c10 = corner(1, -1, 0), c11 = corner(1, 1, 0);
  const r0 = corner(-1, 0, H), r1 = corner(1, 0, H);
  // 6 треугольников: 2 фронтона + 2 ската (как 4 треугольника)
  const tris = [
    c00, c01, r0,      // фронтон A
    c10, c11, r1,      // фронтон B
    c00, r0, r1, c00, r1, c10,  // скат «-b»
    c01, r1, r0, c01, c11, r1,  // скат «+b»
  ];
  // карта -> сцена: (x, y, h) -> (x, h, -y)
  const pos = new Float32Array(tris.length * 3);
  tris.forEach(([x, y, h], i) => {
    pos[i * 3] = x; pos[i * 3 + 1] = h; pos[i * 3 + 2] = -y;
  });
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  geometry.computeVertexNormals();
  const mesh = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({
    color: 0x96422f, flatShading: true, // черепица
  }));
  mesh.castShadow = true;
  return mesh;
}

/** Одно здание -> THREE.Group: коробка с фасадом + крыша/парапет. */
export function buildBuilding(feature) {
  const ring = feature.coordinates; // [[x, y], ...] — внешнее кольцо
  const floors = feature.properties?.floors ?? 1;
  const height = floors * FLOOR_HEIGHT;

  const shape = new THREE.Shape();
  ring.forEach(([x, y], i) => {
    if (i === 0) shape.moveTo(x, y);
    else shape.lineTo(x, y);
  });

  const geometry = new THREE.ExtrudeGeometry(shape, {
    depth: height,
    bevelEnabled: false,
  });
  geometry.rotateX(-Math.PI / 2); // выдавливание теперь идёт вверх (ось Y)

  const color = buildingColor(feature.id, floors);
  // ExtrudeGeometry: группа 0 = крышки (крыша/дно), группа 1 = стены.
  const wallMat = new THREE.MeshStandardMaterial({
    color, map: facadeTexture(),
  });
  const roofMat = new THREE.MeshStandardMaterial({
    color: color.clone().multiplyScalar(0.72),
  });
  const body = new THREE.Mesh(geometry, [roofMat, wallMat]);
  body.castShadow = true;
  body.receiveShadow = true;

  const group = new THREE.Group();
  group.add(body);

  if (floors <= 3) {
    group.add(buildGableRoof(ring, height)); // домик с крышей
  } else {
    // парапет: контур, слегка суженный к центроиду, +1.2 м
    let cx = 0, cy = 0;
    for (const [x, y] of ring) { cx += x; cy += y; }
    cx /= ring.length; cy /= ring.length;
    const inner = new THREE.Shape();
    ring.forEach(([x, y], i) => {
      const px = cx + (x - cx) * 0.93, py = cy + (y - cy) * 0.93;
      if (i === 0) inner.moveTo(px, py);
      else inner.lineTo(px, py);
    });
    const par = new THREE.ExtrudeGeometry(inner, { depth: 1.2, bevelEnabled: false });
    par.rotateX(-Math.PI / 2);
    par.translate(0, height, 0);
    const parapet = new THREE.Mesh(par, roofMat);
    parapet.castShadow = true;
    group.add(parapet);
  }

  group.name = `building:${feature.id}`;
  group.userData = { type: 'building', id: feature.id, floors };
  return group;
}

/** Новое перспективное здание (Точка Б) — полупрозрачное, подсвеченное. */
export function buildNewBuilding(polygon, floors) {
  const feature = {
    id: 'new-building',
    coordinates: polygon,
    properties: { floors },
  };
  const group = buildBuilding(feature);
  group.traverse((o) => {
    if (o.isMesh) {
      o.material = new THREE.MeshStandardMaterial({
        color: 0x00b894,
        transparent: true,
        opacity: 0.75,
        flatShading: true,
      });
    }
  });
  group.name = 'new-building';
  group.userData = { type: 'new-building', floors };
  return group;
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
