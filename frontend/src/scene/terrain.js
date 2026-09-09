// Построение low-poly меша рельефа из ответа /api/terrain/mesh (День 3-4).
// Бэкенд отдаёт плоские массивы:
//   vertices: [x0,y0,z0, x1,y1,z1, ...]
//   faces:    [a0,b0,c0, ...] — индексы вершин треугольников Делоне.
// Здесь мы просто перекладываем их в THREE.BufferGeometry.

import * as THREE from 'three';

// Ось Z на бэкенде — «вверх», в Three.js «вверх» — ось Y.
// Поэтому при переносе вершин меняем (x, y, z) -> (x, z, -y),
// чтобы север карты (рост Y) смотрел «от камеры» (в -Z сцены).
export function buildTerrainMesh(meshData) {
  const { vertices, faces } = meshData;

  const positions = new Float32Array(vertices.length);
  for (let i = 0; i < vertices.length; i += 3) {
    positions[i] = vertices[i];       // x -> x
    positions[i + 1] = vertices[i + 2]; // z (высота) -> y
    positions[i + 2] = -vertices[i + 1]; // y -> -z
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  geometry.setIndex(faces);
  geometry.computeVertexNormals();

  // Цвет по высоте: низины — насыщенно-зелёные, вершины — серо-бурые.
  geometry.computeBoundingBox();
  const { min, max } = geometry.boundingBox;
  const colors = new Float32Array(vertices.length);
  const low = new THREE.Color(0x4e9a51);
  const mid = new THREE.Color(0x8fb573);
  const high = new THREE.Color(0xa89f91);
  const tmp = new THREE.Color();
  const posAttr = geometry.getAttribute('position');
  for (let i = 0; i < posAttr.count; i++) {
    const t = (posAttr.getY(i) - min.y) / Math.max(1e-6, max.y - min.y);
    if (t < 0.5) tmp.lerpColors(low, mid, t * 2);
    else tmp.lerpColors(mid, high, (t - 0.5) * 2);
    colors[i * 3] = tmp.r;
    colors[i * 3 + 1] = tmp.g;
    colors[i * 3 + 2] = tmp.b;
  }
  geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));

  const material = new THREE.MeshStandardMaterial({
    vertexColors: true,
    flatShading: true, // ключевой флаг «low-poly» вида — грани не сглаживаются
  });
  const mesh = new THREE.Mesh(geometry, material);
  mesh.receiveShadow = true; // рельеф принимает тени от зданий и деревьев
  mesh.name = 'terrain';
  return mesh;
}

// Вспомогательное преобразование «картовых» координат (x, y в метрах)
// в координаты сцены — используем для зданий, сетей и точек клика.
export function mapToScene(x, y, height = 0) {
  return new THREE.Vector3(x, height, -y);
}

/**
 * Драпировка объектов по рельефу. Возвращает функцию
 *   (mapX, mapY) -> высота рельефа (scene Y) в этой точке,
 * вычисленную рейкастом вертикально вниз на меш рельефа.
 * Без неё здания и линии «тонут» в холмах.
 */
export function makeHeightSampler(terrainMesh) {
  const ray = new THREE.Raycaster();
  const down = new THREE.Vector3(0, -1, 0);
  const origin = new THREE.Vector3();
  return (mapX, mapY) => {
    origin.set(mapX, 1000, -mapY);
    ray.set(origin, down);
    const hits = ray.intersectObject(terrainMesh, false);
    return hits.length ? hits[0].point.y : 0;
  };
}
