// Корневой компонент приложения (День 1 — связка, День 5 — логика точек).
// Держит всё состояние проекта и связывает панель инструментов с 3D-сценой.

import { useCallback, useEffect, useState } from 'react';
import MapScene from './scene/MapScene.jsx';
import Toolbar from './components/Toolbar.jsx';
import { fetchHealth, fetchLayers, fetchTerrainMesh, postConnect } from './api/client.js';

export default function App() {
  // Данные с бэкенда.
  const [backendOk, setBackendOk] = useState(null);
  const [meshData, setMeshData] = useState(null);   // рельеф (День 3)
  const [layersData, setLayersData] = useState(null); // слои (День 2)

  // Состояние «Точки посадки» (День 5).
  const [mode, setMode] = useState('view'); // view | addBuilding | selectNetwork
  const [floors, setFloors] = useState(5);
  const [buildingSize, setBuildingSize] = useState(40);
  const [newBuilding, setNewBuilding] = useState(null); // Точка Б
  const [selectedNetworkId, setSelectedNetworkId] = useState(null); // Точка А
  const [connection, setConnection] = useState(null); // линия врезки
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  // Первичная загрузка: health-check, затем слои и рельеф.
  useEffect(() => {
    fetchHealth()
      .then(() => setBackendOk(true))
      .catch(() => setBackendOk(false));
    fetchTerrainMesh().then(setMeshData).catch((e) => setError(String(e)));
    fetchLayers().then(setLayersData).catch((e) => setError(String(e)));
  }, []);

  // Клик по рельефу в режиме добавления: ставим квадратное здание (Точка Б).
  const handleTerrainClick = useCallback(
    ([x, y]) => {
      const half = buildingSize / 2;
      const polygon = [
        [x - half, y - half],
        [x + half, y - half],
        [x + half, y + half],
        [x - half, y + half],
        [x - half, y - half], // кольцо замыкаем
      ];
      setNewBuilding({ polygon, center: [x, y], floors });
      setConnection(null);
      setResult(null);
      setError(null);
    },
    [buildingSize, floors],
  );

  // Клик по теплосети (Точка А): запоминаем и, если есть Точка Б, считаем врезку.
  const handleNetworkClick = useCallback(
    (id) => {
      setSelectedNetworkId(id);
      setError(null);
      if (!newBuilding) {
        setError('Сначала добавьте новое здание (Точка Б).');
        return;
      }
      postConnect(newBuilding.polygon, newBuilding.floors, id)
        .then((res) => {
          setConnection(res.connection);
          setResult(res);
        })
        .catch((e) => setError(String(e)));
    },
    [newBuilding],
  );

  // Полный сброс проекта.
  const handleReset = useCallback(() => {
    setNewBuilding(null);
    setSelectedNetworkId(null);
    setConnection(null);
    setResult(null);
    setError(null);
    setMode('view');
  }, []);

  return (
    <div className="app">
      <Toolbar
        mode={mode} setMode={setMode}
        floors={floors} setFloors={setFloors}
        buildingSize={buildingSize} setBuildingSize={setBuildingSize}
        networks={layersData?.layers?.heat_networks ?? []}
        selectedNetworkId={selectedNetworkId}
        result={result} error={error} backendOk={backendOk}
        onReset={handleReset}
      />
      <MapScene
        meshData={meshData} layersData={layersData}
        mode={mode} floors={floors} buildingSize={buildingSize}
        newBuilding={newBuilding} selectedNetworkId={selectedNetworkId}
        connection={connection}
        onTerrainClick={handleTerrainClick} onNetworkClick={handleNetworkClick}
      />
    </div>
  );
}
