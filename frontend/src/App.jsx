// Корневой компонент приложения (Дни 1, 5 и Спринт 2).
// Держит всё состояние проекта и связывает панель Toolbar с 3D-сценой:
//   - при старте проверяет backend и тянет слои карты + меш рельефа;
//   - режим «addBuilding»: клик по рельефу ставит Точку Б (новое здание);
//   - режим «selectNetwork»: клик по теплосети выбирает Точку А —
//     после чего POST /api/route/compute считает ТРИ варианта трассы A*;
//   - бегунки «Штраф за поворот» и «Проход по дорогам» перезапускают
//     расчёт в реальном времени (дебаунс 300 мс).

import { useCallback, useEffect, useRef, useState } from 'react';
import MapScene from './scene/MapScene.jsx';
import Toolbar from './components/Toolbar.jsx';
import { fetchHealth, fetchLayers, fetchTerrainMesh, postRoute } from './api/client.js';

export default function App() {
  // Данные с бэкенда.
  const [backendOk, setBackendOk] = useState(null); // null — проверка идёт
  const [layersData, setLayersData] = useState(null);
  const [meshData, setMeshData] = useState(null);

  // Состояние интерфейса «Точка посадки» (День 5).
  const [mode, setMode] = useState('view'); // view | addBuilding | selectNetwork
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

  // ---------- запуск трассировки ----------
  const runRouting = useCallback((building, networkId, tp, rm) => {
    if (!building || !networkId) return;
    setRouting(true);
    postRoute(building.polygon, building.floors, networkId, tp, rm)
      .then((data) => {
        setRouteData(data);
        // Если выбранный вариант исчез (путь не найден) — берём первый.
        if (!data.variants.some((v) => v.key === selectedRouteKey)) {
          setSelectedRouteKey(data.variants[0]?.key ?? null);
        }
        setError(null);
      })
      .catch((e) => setError(e.message))
      .finally(() => setRouting(false));
  }, [selectedRouteKey]);

  // ---------- клик по рельефу: ставим Точку Б ----------
  const handleTerrainClick = useCallback(
    ([x, y]) => {
      // Новое здание — квадрат со стороной buildingSize, центр в точке клика.
      const h = buildingSize / 2;
      const polygon = [
        [x - h, y - h],
        [x + h, y - h],
        [x + h, y + h],
        [x - h, y + h],
      ];
      const building = { polygon, floors, center: [x, y] };
      setNewBuilding(building);
      setRouteData(null); // старые трассы больше не актуальны
      setError(null);
      if (selectedNetworkId) {
        // Точка А уже выбрана — сразу пересчитываем трассу.
        runRouting(building, selectedNetworkId, turnPenalty, roadMult);
      } else {
        setMode('selectNetwork'); // следующий шаг — выбрать Точку А
      }
    },
    [buildingSize, floors, selectedNetworkId, turnPenalty, roadMult, runRouting],
  );

  // ---------- клик по теплосети: выбираем Точку А и считаем трассы ----------
  const handleNetworkClick = useCallback(
    (networkId) => {
      setSelectedNetworkId(networkId);
      setError(null);
      if (!newBuilding) return; // сначала нужна Точка Б
      runRouting(newBuilding, networkId, turnPenalty, roadMult);
      setMode('view');
    },
    [newBuilding, turnPenalty, roadMult, runRouting],
  );

  // ---------- бегунки: реактивный пересчёт с дебаунсом ----------
  useEffect(() => {
    if (!newBuilding || !selectedNetworkId) return;
    clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(
      () => runRouting(newBuilding, selectedNetworkId, turnPenalty, roadMult),
      300,
    );
    return () => clearTimeout(debounceRef.current);
    // runRouting намеренно не в зависимостях: пересчёт нужен только
    // при изменении самих бегунков.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [turnPenalty, roadMult]);

  // ---------- выбор варианта трассы (в списке или кликом по трубе) ----------
  const handleSelectRoute = useCallback((key) => setSelectedRouteKey(key), []);

  // ---------- сброс проекта ----------
  const handleReset = useCallback(() => {
    setNewBuilding(null);
    setSelectedNetworkId(null);
    setRouteData(null);
    setError(null);
    setMode('view');
  }, []);

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
        error={error}
        onReset={handleReset}
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
        onTerrainClick={handleTerrainClick}
        onNetworkClick={handleNetworkClick}
        onRouteClick={handleSelectRoute}
      />
    </div>
  );
}
