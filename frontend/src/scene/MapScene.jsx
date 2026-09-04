// Главный React-компонент 3D-сцены (Дни 4-5).
// Держит рендерер Three.js, камеру, свет, OrbitControls,
// строит рельеф/здания/сети из данных API и обрабатывает клики
// (расстановка Точки Б и выбор Точки А).

import { useEffect, useRef } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { buildTerrainMesh, mapToScene, makeHeightSampler } from './terrain';
import { buildBuilding, buildNewBuilding, buildMarker, drapeOnTerrain } from './buildings';
import { buildRoads, buildHeatNetworks, highlightHeat, buildConnectionLine } from './networks';

export default function MapScene({
  meshData, layersData, mode, floors, buildingSize,
  newBuilding, selectedNetworkId, connection,
  onTerrainClick, onNetworkClick,
}) {
  const mountRef = useRef(null);
  const stateRef = useRef({}); // «ручка» к живым объектам сцены между эффектами

  // ---------- однократная инициализация сцены ----------
  useEffect(() => {
    const mount = mountRef.current;
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0e1626);
    scene.fog = new THREE.Fog(0x0e1626, 1500, 4000);

    const camera = new THREE.PerspectiveCamera(
      55, mount.clientWidth / mount.clientHeight, 1, 10000,
    );
    camera.position.set(450, 700, 900);

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(mount.clientWidth, mount.clientHeight);
    renderer.setPixelRatio(window.devicePixelRatio);
    mount.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.set(450, 0, -380); // центр демо-карты
    controls.enableDamping = true;

    scene.add(new THREE.AmbientLight(0xffffff, 0.55));
    const sun = new THREE.DirectionalLight(0xffffff, 1.4);
    sun.position.set(600, 900, 400);
    scene.add(sun);
    scene.add(new THREE.GridHelper(1200, 24, 0x2d3a4f, 0x1c2739));

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

    stateRef.current = { scene, camera, renderer, controls };

    return () => {
      cancelAnimationFrame(frameId);
      window.removeEventListener('resize', onResize);
      mount.removeChild(renderer.domElement);
      renderer.dispose();
    };
  }, []);

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

  // ---------- слои карты: здания, дороги, теплосети (Дни 2 и 4) ----------
  useEffect(() => {
    const { scene, sampler } = stateRef.current;
    if (!scene || !layersData || !sampler) return; // ждём рельеф
    for (const name of ['buildings', 'roads', 'heat_networks']) {
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
  }, [layersData, meshData]);

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

  // ---------- линия врезки из ответа бэкенда ----------
  useEffect(() => {
    const { scene, sampler } = stateRef.current;
    if (!scene) return;
    const old = scene.getObjectByName('connection');
    if (old) scene.remove(old);
    if (connection) scene.add(buildConnectionLine(connection, sampler));
  }, [connection]);

  // ---------- обработка кликов (День 5) ----------
  useEffect(() => {
    const { renderer, camera, scene } = stateRef.current;
    if (!renderer) return;

    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();

    const onClick = (event) => {
      const rect = renderer.domElement.getBoundingClientRect();
      pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
      raycaster.setFromCamera(pointer, camera);

      if (mode === 'selectNetwork') {
        // Ищем пересечение с невидимыми «трубами» теплосетей.
        const group = scene.getObjectByName('heat_networks');
        if (!group) return;
        const hits = raycaster.intersectObjects(group.children, false);
        const hit = hits.find((h) => h.object.userData.type === 'heat');
        if (hit) onNetworkClick(hit.object.userData.id);
      } else if (mode === 'addBuilding') {
        const terrain = scene.getObjectByName('terrain');
        if (!terrain) return;
        const [hit] = raycaster.intersectObject(terrain, false);
        if (hit) {
          // Координаты сцены -> координаты карты (x, y): инверсия mapToScene.
          onTerrainClick([hit.point.x, -hit.point.z]);
        }
      }
    };

    renderer.domElement.addEventListener('click', onClick);
    return () => renderer.domElement.removeEventListener('click', onClick);
  }, [mode, onTerrainClick, onNetworkClick, floors, buildingSize]);

  return <div ref={mountRef} className="scene-mount" />;
}
