// Отрисовка оверлеев «всё в одну карту»: НСПД, data.mos.ru, свой GeoJSON.
// Координаты приходят уже в системе сцены (как /api/map/layers):
// [x, y] карты -> mapToScene(x, y, высота рельефа + подъём).
// Полигоны рисуем контурами (LineLoop), линии — Line, точки — маркерами:
// заливка полигонов закрыла бы собой карту, а контур читается поверх неё.

import * as THREE from 'three';
import { mapToScene } from './terrain';

const LIFT = 2.2;        // чуть выше труб (PIPE_LIFT 1.4) — оверлей всегда сверху
const POINT_R = 3.5;     // радиус маркера точечного объекта, м

function linePoints(coords, sampler) {
  return coords.map(([x, y]) => {
    const ground = sampler ? sampler(x, y) : 0;
    return mapToScene(x, y, ground + LIFT);
  });
}

function buildFeature(f, color, sampler) {
  const mat = new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.95 });
  const group = new THREE.Group();
  const t = f.geometry_type;
  const c = f.coordinates;
  const addLine = (pts, loop) => {
    if (pts.length < 2) return;
    const geom = new THREE.BufferGeometry().setFromPoints(linePoints(pts, sampler));
    group.add(loop ? new THREE.LineLoop(geom, mat) : new THREE.Line(geom, mat));
  };
  if (t === 'Polygon') {
    c.forEach((ring) => addLine(ring, true));
  } else if (t === 'MultiPolygon') {
    c.forEach((poly) => poly.forEach((ring) => addLine(ring, true)));
  } else if (t === 'LineString') {
    addLine(c, false);
  } else if (t === 'MultiLineString') {
    c.forEach((line) => addLine(line, false));
  } else if (t === 'Point' || t === 'MultiPoint') {
    const pts = t === 'Point' ? [c] : c;
    const markerGeom = new THREE.SphereGeometry(POINT_R, 10, 8);
    const markerMat = new THREE.MeshBasicMaterial({ color });
    pts.forEach(([x, y]) => {
      const ground = sampler ? sampler(x, y) : 0;
      const marker = new THREE.Mesh(markerGeom, markerMat);
      marker.position.copy(mapToScene(x, y, ground + LIFT + POINT_R));
      group.add(marker);
    });
  }
  return group;
}

/**
 * Строит группу всех оверлеев. Каждый оверлей — подгруппа с именем id,
 * чтобы видимость можно было переключать по чекбоксу.
 */
export function buildOverlays(overlays, hiddenIds, sampler) {
  const root = new THREE.Group();
  root.name = 'overlays';
  for (const ov of overlays ?? []) {
    const g = new THREE.Group();
    g.name = `overlay:${ov.id}`;
    const color = new THREE.Color(ov.color || '#8a5cf6');
    for (const f of ov.features ?? []) {
      g.add(buildFeature(f, color, sampler));
    }
    g.visible = !hiddenIds?.has(ov.id);
    root.add(g);
  }
  return root;
}

/** Переключение видимости одного оверлея без пересборки сцены. */
export function setOverlayVisible(root, id, visible) {
  const g = root?.getObjectByName(`overlay:${id}`);
  if (g) g.visible = visible;
}
