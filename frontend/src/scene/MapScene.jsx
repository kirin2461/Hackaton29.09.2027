// Главный React-компонент 3D-сцены.
// Дни 4-5: рельеф/здания/сети, клики (Точка Б, Точка А).
// День 8: трубы вариантов трассы.
// День 11: TransformControls (gizmo) — перетаскивание узлов трубы.
// День 12: при перетаскивании координаты уходят на валидацию (onPathChange).
// День 14: коллизии — труба краснеет.

import { useEffect, useRef } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { TransformControls } from 'three/addons/controls/TransformControls.js';
import { buildTerrainMesh, mapToScene, makeHeightSampler } from './terrain';
import { buildBuilding, buildNewBuilding, buildMarker, drapeOnTerrain } from './buildings';
import { buildRoads, buildHeatNetworks, highlightHeat } from './networks';
import { buildRoutes, buildPipe } from './routes';
import { buildTrees } from './trees';
import { buildOverlays } from './overlays';

const PIPE_LIFT = 1.4; // как в networks.js
const NODE_COLOR = 0xfdcb6e;      // перетаскиваемые узлы — оранжевые
const NODE_END_COLOR = 0x9fb3d1;  // концевые узлы (врезка/здание) — серые

export default function MapScene({
  meshData, layersData, mode, floors, buildingSize,
  newBuilding, selectedNetworkId, routes, selectedRouteKey,
  editPath, validation, siteScan, xray, showCloud,
  overlays, hiddenOverlays,
  measurePoints, selectedObject, freeCamera,
  onTerrainClick, onNetworkClick, onRouteClick, onPathChange,
  onMeasurePoint, onObjectClick, camTargetRef,
}) {
  const mountRef = useRef(null);
  const stateRef = useRef({}); // «ручка» к живым объектам сцены между эффектами
  const editPathRef = useRef(null); // редактируемая трасса (массив точек)
  const cbRef = useRef({});
  cbRef.current = {
    onTerrainClick, onNetworkClick, onRouteClick, onPathChange,
    onMeasurePoint, onObjectClick, camTargetRef,
  };

  // ---------- однократная инициализация сцены ----------
  useEffect(() => {
    const mount = mountRef.current;
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x87b5d9); // дневное небо
    scene.fog = new THREE.Fog(0x9db8d2, 1600, 4500);

    const camera = new THREE.PerspectiveCamera(
      55, mount.clientWidth / mount.clientHeight, 1, 10000,
    );
    camera.position.set(450, 520, 640);

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(mount.clientWidth, mount.clientHeight);
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.shadowMap.enabled = true; // мягкие тени от зданий и деревьев
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    mount.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.set(450, 0, -380); // центр демо-карты
    controls.enableDamping = true;
    controls.maxPolarAngle = Math.PI * 0.49; // не уходить под землю

    // Небесное рассеянное освещение + солнце с тенями.
    scene.add(new THREE.HemisphereLight(0xbfd9ff, 0x4a6741, 0.9));
    const sun = new THREE.DirectionalLight(0xfff4e0, 1.8);
    sun.position.set(600, 900, 400);
    sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    const S = 750; // теневая камера покрывает всю карту
    sun.shadow.camera.left = -S;
    sun.shadow.camera.right = S;
    sun.shadow.camera.top = S;
    sun.shadow.camera.bottom = -S;
    sun.shadow.camera.far = 3000;
    sun.shadow.bias = -0.0004;
    scene.add(sun);

    // Gizmo (День 11): перетаскивание узлов трубы в плоскости карты.
    const gizmo = new TransformControls(camera, renderer.domElement);
    gizmo.setMode('translate');
    gizmo.showY = false; // высота узла всегда «по рельефу»
    const gizmoHelper = typeof gizmo.getHelper === 'function' ? gizmo.getHelper() : gizmo;
    scene.add(gizmoHelper);
    gizmo.addEventListener('dragging-changed', (e) => {
      controls.enabled = !e.value; // пока тянем узел — орбита выключена
    });
    gizmo.addEventListener('objectChange', () => {
      const node = gizmo.object;
      const st = stateRef.current;
      if (!node || node.userData.pathIdx === undefined || !editPathRef.current) return;
      // Сцена -> карта: x = pos.x, y = -pos.z; высоту берём с рельефа.
      const x = node.position.x;
      const y = -node.position.z;
      const ground = st.sampler ? st.sampler(x, y) : 0;
      node.position.y = ground + PIPE_LIFT;
      const path = editPathRef.current.map((p) => [...p]);
      path[node.userData.pathIdx] = [x, y];
      editPathRef.current = path;
      rebuildEditedPipe(); // труба следует за узлом вживую
      cbRef.current.onPathChange?.(path); // реактивная валидация (День 12)
    });

    // Цикл отрисовки.
    let frameId;
    const animate = () => {
      frameId = requestAnimationFrame(animate);
      controls.update();
      renderer.render(scene, camera);
    };
    animate();

    // Подгон размера под окно.
    const onResize = () => {
      camera.aspect = mount.clientWidth / mount.clientHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(mount.clientWidth, mount.clientHeight);
    };
    window.addEventListener('resize', onResize);

    stateRef.current = { scene, camera, renderer, controls, gizmo, gizmoHelper, sun };
    window.__scene = scene; // для экспорта GLB (День 16)
    window.__gizmoHelper = gizmoHelper;

    return () => {
      cancelAnimationFrame(frameId);
      window.removeEventListener('resize', onResize);
      gizmo.detach();
      gizmo.dispose();
      mount.removeChild(renderer.domElement);
      renderer.dispose();
    };
  }, []);

  // ---------- центровка камеры и солнца на охвате карты ----------
  useEffect(() => {
    const { camera, controls, sun } = stateRef.current;
    if (!camera || !layersData?.bounds) return;
    const [x0, y0, x1, y1] = layersData.bounds;
    const cx = (x0 + x1) / 2;
    const cy = (y0 + y1) / 2;
    const size = Math.max(x1 - x0, y1 - y0);
    controls.target.set(cx, 0, -cy);
    camera.position.set(cx + size * 0.05, size * 0.55, -cy + size * 0.62);
    // Теневая камера солнца накрывает всю карту, а не фиксированный квадрат.
    sun.position.set(cx + size * 0.4, size * 0.75, -cy + size * 0.3);
    sun.target.position.set(cx, 0, -cy);
    sun.target.updateMatrixWorld();
    const s = size * 0.75;
    sun.shadow.camera.left = -s;
    sun.shadow.camera.right = s;
    sun.shadow.camera.top = s;
    sun.shadow.camera.bottom = -s;
    sun.shadow.camera.updateProjectionMatrix();
    controls.update();
  }, [layersData]);

  // ---------- рельеф (День 3-4) ----------
  useEffect(() => {
    const { scene } = stateRef.current;
    if (!scene || !meshData) return;
    const old = scene.getObjectByName('terrain');
    if (old) scene.remove(old);
    const terrain = buildTerrainMesh(meshData);
    scene.add(terrain);
    // Сэмплер высоты рельефа — нужен для драпировки зданий и линий.
    stateRef.current.sampler = makeHeightSampler(terrain);
  }, [meshData]);

  // ---------- слои карты: здания, дороги, теплосети, деревья ----------
  useEffect(() => {
    const { scene, sampler } = stateRef.current;
    if (!scene || !layersData || !sampler) return; // ждём рельеф
    for (const name of ['buildings', 'roads', 'heat_networks', 'trees']) {
      const old = scene.getObjectByName(name);
      if (old) scene.remove(old);
    }
    const bGroup = new THREE.Group();
    bGroup.name = 'buildings';
    layersData.layers.buildings.forEach((f) => {
      const mesh = buildBuilding(f);
      drapeOnTerrain(mesh, sampler, f.coordinates);
      bGroup.add(mesh);
    });
    scene.add(bGroup);
    scene.add(buildRoads(layersData.layers.roads, sampler));
    scene.add(buildHeatNetworks(layersData.layers.heat_networks, sampler));
    scene.add(buildTrees(layersData, layersData.bounds, sampler));
  }, [layersData, meshData]);

  // ---------- оверлеи «всё в одну карту»: НСПД / data.mos.ru / GeoJSON ----------
  useEffect(() => {
    const { scene, sampler } = stateRef.current;
    if (!scene || !sampler) return; // ждём рельеф
    const old = scene.getObjectByName('overlays');
    if (old) scene.remove(old);
    scene.add(buildOverlays(overlays, hiddenOverlays, sampler));
  }, [overlays, hiddenOverlays, meshData]);

  // ---------- новое здание / маркер Точки Б (День 5) ----------
  useEffect(() => {
    const { scene, sampler } = stateRef.current;
    if (!scene) return;
    for (const name of ['new-building', 'marker-b']) {
      const old = scene.getObjectByName(name);
      if (old) scene.remove(old);
    }
    if (newBuilding) {
      const mesh = buildNewBuilding(newBuilding.polygon, newBuilding.floors);
      drapeOnTerrain(mesh, sampler, newBuilding.polygon);
      scene.add(mesh);
      const [cx, cy] = newBuilding.center;
      const ground = sampler ? sampler(cx, cy) : 0;
      const marker = buildMarker(mapToScene(cx, cy, ground + newBuilding.floors * 3 + 8));
      marker.name = 'marker-b';
      scene.add(marker);
    }
  }, [newBuilding, meshData]);

  // ---------- подсветка выбранной теплосети (Точка А) ----------
  useEffect(() => {
    const { scene } = stateRef.current;
    const group = scene?.getObjectByName('heat_networks');
    if (group) highlightHeat(group, selectedNetworkId);
  }, [selectedNetworkId, layersData]);

  // ---------- варианты трассы A* (День 8) ----------
  useEffect(() => {
    const { scene, sampler } = stateRef.current;
    if (!scene) return;
    const old = scene.getObjectByName('routes');
    if (old) scene.remove(old);
    if (routes && routes.length) {
      const group = buildRoutes(routes, selectedRouteKey, sampler);
      group.visible = mode !== 'editRoute'; // в редакторе видна только живая труба
      scene.add(group);
    }
  }, [routes, selectedRouteKey, meshData, mode]);

  // ---------- режим редактирования: узлы + «живая труба» (День 11) ----------
  const rebuildEditNodes = () => {
    const { scene, sampler } = stateRef.current;
    if (!scene || !editPathRef.current) return;
    const old = scene.getObjectByName('edit-nodes');
    if (old) scene.remove(old);
    const group = new THREE.Group();
    group.name = 'edit-nodes';
    editPathRef.current.forEach(([x, y], i) => {
      const n = editPathRef.current.length;
      const isEnd = i === 0 || i === n - 1;
      const ground = sampler ? sampler(x, y) : 0;
      const node = new THREE.Mesh(
        new THREE.SphereGeometry(isEnd ? 1.8 : 2.6, 14, 14),
        new THREE.MeshStandardMaterial({
          color: isEnd ? NODE_END_COLOR : NODE_COLOR,
          emissive: isEnd ? 0x000000 : 0x7a5c00,
          emissiveIntensity: 0.5,
        }),
      );
      node.position.copy(mapToScene(x, y, ground + PIPE_LIFT));
      node.userData = { type: 'pipe-node', pathIdx: i, draggable: !isEnd };
      group.add(node);
    });
    scene.add(group);
  };

  const rebuildEditedPipe = () => {
    const { scene, sampler } = stateRef.current;
    if (!scene || !editPathRef.current) return;
    const old = scene.getObjectByName('edited-route');
    if (old) scene.remove(old);
    const collision = stateRef.current.collision;
    const pipe = buildPipe(
      { key: 'edited', path: editPathRef.current,
        color: collision ? '#ff4757' : '#fdcb6e' },
      true, sampler,
    );
    if (pipe) {
      pipe.name = 'edited-route';
      scene.add(pipe);
    }
  };

  // Вход/выход из режима редактирования.
  useEffect(() => {
    const { scene, gizmo } = stateRef.current;
    if (!scene || !gizmo) return;
    if (mode === 'editRoute' && editPath) {
      editPathRef.current = editPath.map((p) => [...p]);
      rebuildEditNodes();
      rebuildEditedPipe();
    } else {
      gizmo.detach();
      editPathRef.current = null;
      for (const name of ['edit-nodes', 'edited-route']) {
        const old = scene.getObjectByName(name);
        if (old) scene.remove(old);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode]);

  // ---------- коллизия: труба краснеет (День 14) ----------
  useEffect(() => {
    stateRef.current.collision = Boolean(validation?.collision);
    if (mode === 'editRoute') rebuildEditedPipe();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [validation]);

  // ---------- обработка кликов (Дни 5, 8, 11) ----------
  useEffect(() => {
    const { renderer, camera, scene, gizmo } = stateRef.current;
    if (!renderer) return;

    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();

    const onClick = (event) => {
      const rect = renderer.domElement.getBoundingClientRect();
      pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
      raycaster.setFromCamera(pointer, camera);
      const cb = cbRef.current;

      if (mode === 'editRoute') {
        // Клик по узлу — цепляем gizmo; клик мимо — отцепляем.
        const nodes = scene.getObjectByName('edit-nodes');
        if (!nodes) return;
        const hits = raycaster.intersectObjects(nodes.children, false);
        const hit = hits.find((h) => h.object.userData.draggable);
        if (hit) gizmo.attach(hit.object);
        else gizmo.detach();
      } else if (mode === 'selectNetwork') {
        const group = scene.getObjectByName('heat_networks');
        if (!group) return;
        const hits = raycaster.intersectObjects(group.children, false);
        const hit = hits.find((h) => h.object.userData.type === 'heat');
        if (hit) cb.onNetworkClick?.(hit.object.userData.id);
      } else if (mode === 'measure' || mode === 'object') {
        // Геодезия и паспорт объекта: клик по рельефу → координаты карты.
        const terrain = scene.getObjectByName('terrain');
        if (!terrain) return;
        const [hit] = raycaster.intersectObject(terrain, false);
        if (!hit) return;
        const mapPoint = [hit.point.x, -hit.point.z];
        if (mode === 'measure') cb.onMeasurePoint?.(mapPoint);
        else cb.onObjectClick?.(mapPoint);
      } else if (mode === 'addBuilding') {
        const terrain = scene.getObjectByName('terrain');
        if (!terrain) return;
        const [hit] = raycaster.intersectObject(terrain, false);
        if (hit) {
          // Координаты сцены -> координаты карты (x, y): инверсия mapToScene.
          cb.onTerrainClick?.([hit.point.x, -hit.point.z]);
        }
      } else {
        // Режим обзора: клик по трубе варианта — выбрать этот вариант.
        const group = scene.getObjectByName('routes');
        if (!group) return;
        const hits = raycaster.intersectObjects(group.children, false);
        const hit = hits.find((h) => h.object.userData.type === 'route');
        if (hit) cb.onRouteClick?.(hit.object.userData.key);
      }
    };

    renderer.domElement.addEventListener('click', onClick);
    return () => renderer.domElement.removeEventListener('click', onClick);
  }, [mode, floors, buildingSize]);


  // ---------- геодезия: линия измерения и маркеры точек ----------
  useEffect(() => {
    const { scene, sampler } = stateRef.current;
    if (!scene) return;
    const old = scene.getObjectByName('measure');
    if (old) scene.remove(old);
    if (!measurePoints?.length) return;
    const group = new THREE.Group();
    group.name = 'measure';
    const mat = new THREE.LineBasicMaterial({ color: 0xffeaa7 });
    const pts = measurePoints.map(([x, y]) => {
      const g = sampler ? sampler(x, y) : 0;
      return mapToScene(x, y, g + 2.5);
    });
    if (pts.length >= 2) {
      group.add(new THREE.Line(
        new THREE.BufferGeometry().setFromPoints(pts), mat));
    }
    const markerGeom = new THREE.SphereGeometry(2.2, 10, 8);
    const markerMat = new THREE.MeshBasicMaterial({ color: 0xffeaa7 });
    pts.forEach((p) => {
      const mk = new THREE.Mesh(markerGeom, markerMat);
      mk.position.copy(p);
      group.add(mk);
    });
    scene.add(group);
  }, [measurePoints, meshData]);

  // ---------- паспорт: контур выбранного объекта ----------
  useEffect(() => {
    const { scene, sampler } = stateRef.current;
    if (!scene) return;
    const old = scene.getObjectByName('selected-object');
    if (old) scene.remove(old);
    if (!selectedObject?.length) return;
    const mat = new THREE.LineBasicMaterial({ color: 0x00e5ff, linewidth: 2 });
    const pts = selectedObject.map(([x, y]) => {
      const g = sampler ? sampler(x, y) : 0;
      return mapToScene(x, y, g + 3.0);
    });
    const loop = new THREE.LineLoop(
      new THREE.BufferGeometry().setFromPoints(pts), mat);
    loop.name = 'selected-object';
    scene.add(loop);
  }, [selectedObject, meshData]);

  // ---------- геттер точки камеры для синхронной карты ----------
  useEffect(() => {
    if (!camTargetRef) return;
    camTargetRef.current = () => {
      const { controls } = stateRef.current;
      if (!controls) return [0, 0];
      // Сцена -> карта: x = target.x, y = -target.z
      return [controls.target.x, -controls.target.z];
    };
  }, [camTargetRef]);

  // ---------- свободная камера: pan без закреплённой точки + WASD ----------
  useEffect(() => {
    const { controls, camera } = stateRef.current;
    if (!controls || !camera) return;
    controls.enablePan = true; // панорамирование правой кнопкой — всегда
    controls.maxPolarAngle = freeCamera ? Math.PI * 0.95 : Math.PI * 0.49;
    controls.screenSpacePanning = Boolean(freeCamera);
    if (!freeCamera) return undefined;

    // WASD / стрелки: двигаем и камеру, и цель — карта «плывёт».
    const STEP = 40;
    const onKey = (e) => {
      if (e.target instanceof HTMLInputElement) return; // не красть ввод из полей
      const dir = new THREE.Vector3();
      camera.getWorldDirection(dir);
      dir.y = 0;
      dir.normalize();
      const right = new THREE.Vector3().crossVectors(dir, new THREE.Vector3(0, 1, 0));
      const move = new THREE.Vector3();
      const k = e.key.toLowerCase();
      if (k === 'w' || k === 'arrowup') move.add(dir);
      else if (k === 's' || k === 'arrowdown') move.sub(dir);
      else if (k === 'a' || k === 'arrowleft') move.sub(right);
      else if (k === 'd' || k === 'arrowright') move.add(right);
      else return;
      e.preventDefault();
      move.multiplyScalar(STEP);
      camera.position.add(move);
      controls.target.add(move);
      controls.update();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [freeCamera]);

  // ---------- маркеры топ-площадок (обратная задача) ----------
  useEffect(() => {
    const { scene, sampler } = stateRef.current;
    if (!scene) return;
    const old = scene.getObjectByName('site-markers');
    if (old) scene.remove(old);
    if (!siteScan?.top?.length) return;
    const group = new THREE.Group();
    group.name = 'site-markers';
    siteScan.top.forEach((t) => {
      // Контур площадки — жёлтая рамка на рельефе.
      const pts = t.polygon.map(([x, y]) => {
        const g = sampler ? sampler(x, y) : 0;
        return mapToScene(x, y, g + 0.6);
      });
      const geo = new THREE.BufferGeometry().setFromPoints(pts);
      group.add(new THREE.Line(
        geo, new THREE.LineBasicMaterial({ color: 0xffd166 }),
      ));
      // Номер в рейтинге — спрайт над центром площадки.
      const [cx, cy] = t.center;
      const g = sampler ? sampler(cx, cy) : 0;
      const sprite = makeRankSprite(t.rank);
      sprite.position.copy(mapToScene(cx, cy, g + 20));
      sprite.scale.set(16, 16, 1);
      group.add(sprite);
    });
    scene.add(group);
  }, [siteScan, meshData]);

  // ---------- рентген-режим: земля прозрачная, трубы на глубине ----------
  useEffect(() => {
    const { scene, sampler, controls } = stateRef.current;
    if (!scene) return;
    const terrain = scene.getObjectByName('terrain');
    const buildingsG = scene.getObjectByName('buildings');
    const roadsG = scene.getObjectByName('roads');
    const trees = scene.getObjectByName('trees');
    const old = scene.getObjectByName('xray-pipes');
    if (old) scene.remove(old);

    const setOpacity = (obj, opacity) => {
      if (!obj) return;
      obj.traverse((o) => {
        if (o.isMesh && o.material) {
          o.material.transparent = opacity < 1;
          o.material.opacity = opacity;
          o.material.depthWrite = opacity >= 1;
          o.material.needsUpdate = true;
        }
      });
    };
    // Облако точек читается лучше на приглушённом рельефе.
    const dimForCloud = (opacity) => setOpacity(terrain, opacity);

    if (!xray) {
      dimForCloud(showCloud ? 0.28 : 1);
      setOpacity(buildingsG, 1);
      setOpacity(roadsG, 1);
      if (trees) trees.visible = true;
      if (controls) controls.maxPolarAngle = Math.PI * 0.49;
      return;
    }

    setOpacity(terrain, 0.22);
    setOpacity(buildingsG, 0.3);
    setOpacity(roadsG, 0.25);
    dimForCloud(0.22); // рентген приоритетнее облака
    if (trees) trees.visible = false;
    if (controls) controls.maxPolarAngle = Math.PI * 0.8; // заглянуть снизу

    const group = new THREE.Group();
    group.name = 'xray-pipes';
    const addUnderground = (coords, depth, color, radius) => {
      if (!coords || coords.length < 2) return;
      const pts = coords.map(([x, y]) => {
        const g = sampler ? sampler(x, y) : 0;
        return mapToScene(x, y, g - depth);
      });
      const curve = new THREE.CatmullRomCurve3(pts, false, 'catmullrom', 0.0);
      group.add(new THREE.Mesh(
        new THREE.TubeGeometry(curve, Math.max(16, pts.length * 4), radius, 8, false),
        new THREE.MeshStandardMaterial({
          color, emissive: color, emissiveIntensity: 0.8,
        }),
      ));
    };
    // Существующие теплотрассы — нормативная глубина заложения −2 м.
    (layersData?.layers?.heat_networks ?? []).forEach((f) =>
      addUnderground(f.coordinates, 2.0, 0xff6b35, 1.6));
    // Новая трасса — −3 м (подземная канальная прокладка).
    const v = routes?.find((x) => x.key === selectedRouteKey);
    if (v) addUnderground(v.path, 3.0, 0x00e5ff, 2.0);
    scene.add(group);
  }, [xray, showCloud, layersData, routes, selectedRouteKey, meshData]);

  // ---------- облако лидарных точек (вау-режим) ----------
  useEffect(() => {
    const { scene } = stateRef.current;
    if (!scene) return;
    const old = scene.getObjectByName('lidar-cloud');
    if (old) {
      old.geometry.dispose();
      old.material.dispose();
      scene.remove(old);
    }
    if (!showCloud) return;

    let cancelled = false;
    fetch('/api/terrain/lidar/cloud.bin')
      .then((r) => (r.ok ? r.arrayBuffer() : Promise.reject(r.status)))
      .then((buf) => {
        if (cancelled) return;
        const dv = new DataView(buf);
        const n = dv.getUint32(0, true);
        const pos = new Float32Array(buf, 4, n * 3);
        const col = new Uint8Array(buf, 4 + n * 12, n * 3);

        // Карта (x, y, z) -> сцена (x, z, -y), как в buildTerrainMesh.
        const positions = new Float32Array(n * 3);
        const colors = new Float32Array(n * 3);
        for (let i = 0; i < n; i++) {
          positions[i * 3] = pos[i * 3];
          positions[i * 3 + 1] = pos[i * 3 + 2];
          positions[i * 3 + 2] = -pos[i * 3 + 1];
          colors[i * 3] = col[i * 3] / 255;
          colors[i * 3 + 1] = col[i * 3 + 1] / 255;
          colors[i * 3 + 2] = col[i * 3 + 2] / 255;
        }
        const geometry = new THREE.BufferGeometry();
        geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
        geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
        const points = new THREE.Points(
          geometry,
          new THREE.PointsMaterial({
            size: 2.2,
            vertexColors: true,
            sizeAttenuation: true,
          }),
        );
        points.name = 'lidar-cloud';
        scene.add(points);
      })
      .catch(() => {}); // облако опционально — молча пропускаем сбой
    return () => { cancelled = true; };
  }, [showCloud, meshData]);

  return <div ref={mountRef} className="scene-mount" />;
}

/** Спрайт с номером площадки в рейтинге (canvas → текстура). */
function makeRankSprite(rank) {
  const canvas = document.createElement('canvas');
  canvas.width = 128;
  canvas.height = 128;
  const ctx = canvas.getContext('2d');
  ctx.beginPath();
  ctx.arc(64, 64, 56, 0, Math.PI * 2);
  ctx.fillStyle = '#ffd166';
  ctx.fill();
  ctx.lineWidth = 8;
  ctx.strokeStyle = '#1c2833';
  ctx.stroke();
  ctx.fillStyle = '#1c2833';
  ctx.font = 'bold 64px sans-serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(String(rank), 64, 68);
  const sprite = new THREE.Sprite(
    new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(canvas) }),
  );
  return sprite;
}
