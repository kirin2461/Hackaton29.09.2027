// Корневой компонент приложения (Дни 1 и 5).
// Держит всё состояние проекта и связывает панель Toolbar с 3D-сценой:
//   - при старте проверяет backend и тянет слои карты + меш рельефа;
//   - режим «addBuilding»: клик по рельефу ставит Точку Б (новое здание);
//   - режим «selectNetwork»: клик по теплосети выбирает Точку А,
//     после чего уходит POST /api/project/connect на расчёт врезки.

import { useCallback, useEffect, useState } from 'react';
import MapScene from './scene/MapScene.jsx';
import Toolbar from './components/Toolbar.jsx';
import { fetchHealth, fetchLayers, fetchTerrainMesh, postConnect } from './api/client.js';

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
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

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
      setNewBuilding({ polygon, floors, center: [x, y] });
      setResult(null); // старый расчёт больше не актуален
      setError(null);
      setMode('selectNetwork'); // следующий шаг — выбрать Точку А
    },
    [buildingSize, floors],
  );

  // ---------- клик по теплосети: выбираем Точку А и считаем врезку ----------
  const handleNetworkClick = useCallback(
    (networkId) => {
      setSelectedNetworkId(networkId);
      setError(null);
      if (!newBuilding) return; // сначала нужна Точка Б
      postConnect(newBuilding.polygon, newBuilding.floors, networkId)
        .then(setResult)
        .catch((e) => setError(e.message));
    },
    [newBuilding],
  );

  // ---------- сброс проекта ----------
  const handleReset = useCallback(() => {
    setNewBuilding(null);
    setSelectedNetworkId(null);
    setResult(null);
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
        result={result}
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
        connection={result?.connection ?? null}
        onTerrainClick={handleTerrainClick}
        onNetworkClick={handleNetworkClick}
      />
    </div>
  );
}
