// Корневой компонент приложения.
// Спринт 1: связка Toolbar ↔ 3D-сцена, Точка А/Б.
// Спринт 2: A*-трассировка, 3 варианта, бегунки штрафов.
// Спринт 3: gizmo-редактирование трубы, реактивная валидация,
//           смета/гидравлика, блокировка сохранения при коллизии.
// Спринт 4: экспорт сцены в .glb для Blender.

import { useCallback, useEffect, useRef, useState } from 'react';
import MapScene from './scene/MapScene.jsx';
import Toolbar from './components/Toolbar.jsx';
import {
  fetchHealth, fetchLayers, fetchTerrainMesh,
  postRoute, postValidate, postSave,
} from './api/client.js';
import { exportSceneGLB } from './scene/exportGlb.js';

export default function App() {
  // Данные с бэкенда.
  const [backendOk, setBackendOk] = useState(null); // null — проверка идёт
  const [layersData, setLayersData] = useState(null);
  const [meshData, setMeshData] = useState(null);

  // Состояние интерфейса «Точка посадки» (День 5).
  const [mode, setMode] = useState('view'); // view | addBuilding | selectNetwork | editRoute
  const [floors, setFloors] = useState(5);
  const [buildingSize, setBuildingSize] = useState(30);
  const [newBuilding, setNewBuilding] = useState(null); // {polygon, floors, center}
  const [selectedNetworkId, setSelectedNetworkId] = useState(null);
  const [error, setError] = useState(null);

  // Трассировка A* (Спринт 2).
  const [routeData, setRouteData] = useState(null); // ответ /api/route/compute
  const [selectedRouteKey, setSelectedRouteKey] = useState('balanced');
  const [turnPenalty, setTurnPenalty] = useState(2); // штраф за 45° поворота
  const [roadMult, setRoadMult] = useState(4); // множитель стоимости дорог
  const [routing, setRouting] = useState(false); // идёт пересчёт
  const debounceRef = useRef(null);

  // Редактирование и валидация трубы (Спринт 3).
  const [editPath, setEditPath] = useState(null); // точки редактируемой трассы
  const [validation, setValidation] = useState(null); // ответ /api/route/validate
  const [savedId, setSavedId] = useState(null);
  const validateRef = useRef(null);

  // ---------- загрузка данных при старте ----------
  useEffect(() => {
    fetchHealth()
      .then(() => setBackendOk(true))
      .catch(() => setBackendOk(false));

    Promise.all([fetchLayers(), fetchTerrainMesh()])
      .then(([layers, mesh]) => {
        setLayersData(layers);
        setMeshData(mesh);
      })
      .catch((e) => setError(`Не удалось загрузить карту: ${e.message}`));
  }, []);

  // ---------- валидация трассы (День 12-13) ----------
  const runValidation = useCallback((path) => {
    if (!path || path.length < 2) return;
    postValidate(path)
      .then(setValidation)
      .catch(() => setValidation(null));
  }, []);

  // ---------- запуск трассировки ----------
  const runRouting = useCallback((building, networkId, tp, rm) => {
    if (!building || !networkId) return;
    setRouting(true);
    postRoute(building.polygon, building.floors, networkId, tp, rm)
      .then((data) => {
        setRouteData(data);
        setSavedId(null);
        if (!data.variants.some((v) => v.key === selectedRouteKey)) {
          setSelectedRouteKey(data.variants[0]?.key ?? null);
        }
        setError(null);
      })
      .catch((e) => setError(e.message))
      .finally(() => setRouting(false));
  }, [selectedRouteKey]);

  // Смета для выбранного варианта (показывается сразу после A*).
  useEffect(() => {
    if (mode === 'editRoute') return; // при редактировании считаем editPath
    const v = routeData?.variants?.find((x) => x.key === selectedRouteKey);
    if (v) runValidation(v.path);
  }, [routeData, selectedRouteKey, mode, runValidation]);

  // ---------- клик по рельефу: ставим Точку Б ----------
  const handleTerrainClick = useCallback(
    ([x, y]) => {
      const h = buildingSize / 2;
      const polygon = [
        [x - h, y - h],
        [x + h, y - h],
        [x + h, y + h],
        [x - h, y + h],
      ];
      const building = { polygon, floors, center: [x, y] };
      setNewBuilding(building);
      setRouteData(null);
      setValidation(null);
      setSavedId(null);
      setError(null);
      if (selectedNetworkId) {
        runRouting(building, selectedNetworkId, turnPenalty, roadMult);
      } else {
        setMode('selectNetwork');
      }
    },
    [buildingSize, floors, selectedNetworkId, turnPenalty, roadMult, runRouting],
  );

  // ---------- клик по теплосети: Точка А + трассы ----------
  const handleNetworkClick = useCallback(
    (networkId) => {
      setSelectedNetworkId(networkId);
      setError(null);
      if (!newBuilding) return;
      runRouting(newBuilding, networkId, turnPenalty, roadMult);
      setMode('view');
    },
    [newBuilding, turnPenalty, roadMult, runRouting],
  );

  // ---------- бегунки: реактивный пересчёт с дебаунсом ----------
  useEffect(() => {
    if (!newBuilding || !selectedNetworkId || mode === 'editRoute') return;
    clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(
      () => runRouting(newBuilding, selectedNetworkId, turnPenalty, roadMult),
      300,
    );
    return () => clearTimeout(debounceRef.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [turnPenalty, roadMult]);

  // ---------- выбор варианта трассы ----------
  const handleSelectRoute = useCallback((key) => {
    setMode('view'); // смена варианта завершает редактирование
    setEditPath(null);
    setSelectedRouteKey(key);
    setSavedId(null);
  }, []);

  // ---------- редактирование трубы (День 11-12) ----------
  const handleStartEdit = useCallback(() => {
    const v = routeData?.variants?.find((x) => x.key === selectedRouteKey);
    if (!v) return;
    setEditPath(v.path.map((p) => [...p]));
    setMode('editRoute');
  }, [routeData, selectedRouteKey]);

  const handleFinishEdit = useCallback(() => {
    setMode('view');
  }, []);

  // Живой перетаскивание узла: обновляем путь, валидация с дебаунсом.
  const handlePathChange = useCallback((path) => {
    setEditPath(path);
    setSavedId(null);
    clearTimeout(validateRef.current);
    validateRef.current = setTimeout(() => runValidation(path), 300);
  }, [runValidation]);

  // ---------- сохранение (День 14-15) ----------
  const currentPath = () => {
    if (mode === 'editRoute' && editPath) return editPath;
    return routeData?.variants?.find((x) => x.key === selectedRouteKey)?.path ?? null;
  };

  const handleSave = useCallback(() => {
    const path = currentPath();
    if (!path || !newBuilding || !selectedNetworkId) return;
    const variant = mode === 'editRoute' ? 'custom' : selectedRouteKey;
    postSave(newBuilding.polygon, newBuilding.floors, selectedNetworkId, path, variant)
      .then((r) => { setSavedId(r.project_id); setError(null); })
      .catch((e) => setError(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, editPath, routeData, selectedRouteKey, newBuilding, selectedNetworkId]);

  // ---------- сброс проекта ----------
  const handleReset = useCallback(() => {
    setNewBuilding(null);
    setSelectedNetworkId(null);
    setRouteData(null);
    setValidation(null);
    setEditPath(null);
    setSavedId(null);
    setError(null);
    setMode('view');
  }, []);

  // ---------- демо-сценарий в один клик (для показа жюри) ----------
  // Ставит 9-этажку на свободную площадку (300, 800) у дальнего края
  // карты и строит трассы к теплосети h2: варианты заметно различаются,
  // что наглядно показывает работу штрафов.
  const handleDemo = useCallback(() => {
    const cx = 300, cy = 800, h = 20;
    const polygon = [
      [cx - h, cy - h],
      [cx + h, cy - h],
      [cx + h, cy + h],
      [cx - h, cy + h],
    ];
    const building = { polygon, floors: 9, center: [cx, cy] };
    setNewBuilding(building);
    setSelectedNetworkId('h2');
    setRouteData(null);
    setValidation(null);
    setEditPath(null);
    setSavedId(null);
    setError(null);
    setMode('view');
    runRouting(building, 'h2', turnPenalty, roadMult);
  }, [runRouting, turnPenalty, roadMult]);

  const networks = layersData?.layers?.heat_networks ?? [];

  return (
    <div className="app">
      <Toolbar
        mode={mode}
        setMode={setMode}
        floors={floors}
        setFloors={setFloors}
        buildingSize={buildingSize}
        setBuildingSize={setBuildingSize}
        networks={networks}
        selectedNetworkId={selectedNetworkId}
        onPickNetwork={handleNetworkClick}
        routeData={routeData}
        routing={routing}
        selectedRouteKey={selectedRouteKey}
        onSelectRoute={handleSelectRoute}
        turnPenalty={turnPenalty}
        setTurnPenalty={setTurnPenalty}
        roadMult={roadMult}
        setRoadMult={setRoadMult}
        validation={validation}
        savedId={savedId}
        onStartEdit={handleStartEdit}
        onFinishEdit={handleFinishEdit}
        onSave={handleSave}
        onExport={() => exportSceneGLB()}
        error={error}
        onReset={handleReset}
        onDemo={handleDemo}
        backendOk={backendOk}
      />
      <MapScene
        meshData={meshData}
        layersData={layersData}
        mode={mode}
        floors={floors}
        buildingSize={buildingSize}
        newBuilding={newBuilding}
        selectedNetworkId={selectedNetworkId}
        routes={routeData?.variants ?? null}
        selectedRouteKey={selectedRouteKey}
        editPath={editPath}
        validation={validation}
        onTerrainClick={handleTerrainClick}
        onNetworkClick={handleNetworkClick}
        onRouteClick={handleSelectRoute}
        onPathChange={handlePathChange}
      />
    </div>
  );
}
