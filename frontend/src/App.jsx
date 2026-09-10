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
  fetchHealth, fetchLayers, fetchTerrainMesh, fetchNetworkStats,
  fetchPresets, postRoute, postValidate, postSave, postScan, postLoadBbox,
  fetchLidarStatus, postLidarDemo, postLidarClear, postLidarUpload,
  postPareto, postReportPdf,
  fetchOverlays, postGeojsonOverlay, deleteOverlay,
  postNspdOverlay, postDatamosOverlay,
} from './api/client.js';
import { exportSceneGLB } from './scene/exportGlb.js';
import { boxIntersectsPolygon, distToPolyline } from './scene/geo.js';

export default function App() {
  // Данные с бэкенда.
  const [backendOk, setBackendOk] = useState(null); // null — проверка идёт
  const [layersData, setLayersData] = useState(null);
  const [meshData, setMeshData] = useState(null);
  const [netStats, setNetStats] = useState(null); // метрики живучести сети

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

  // Обратная задача: сканирование площадок (top-N по цене присоединения).
  const [siteScan, setSiteScan] = useState(null); // ответ /api/route/scan
  const [scanning, setScanning] = useState(false);

  // Рентген-режим: полупрозрачная земля, трубы на глубине заложения.
  const [xray, setXray] = useState(false);

  // Загрузка произвольного района из OSM.
  const [presets, setPresets] = useState([]);
  const [districtLoading, setDistrictLoading] = useState(false);

  // Парето-анализ «цена ↔ надёжность».
  const [paretoData, setParetoData] = useState(null);
  const [paretoBusy, setParetoBusy] = useState(false);
  const [pdfBusy, setPdfBusy] = useState(false);

  // Оверлеи «всё в одну карту»: НСПД, data.mos.ru, свой GeoJSON.
  const [overlays, setOverlays] = useState([]);
  const [hiddenOverlays, setHiddenOverlays] = useState(new Set());
  const [overlayBusy, setOverlayBusy] = useState(false);

  // Лидарный рельеф (LAS/LAZ) и облако точек.
  const [lidarStatus, setLidarStatus] = useState(null);
  const [lidarBusy, setLidarBusy] = useState(false);
  const [showCloud, setShowCloud] = useState(false);

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

    fetchNetworkStats()
      .then(setNetStats)
      .catch(() => setNetStats(null)); // метрики опциональны

    fetchPresets()
      .then((d) => setPresets(d.presets ?? []))
      .catch(() => setPresets([]));

    fetchLidarStatus()
      .then(setLidarStatus)
      .catch(() => setLidarStatus(null));

    fetchOverlays()
      .then((d) => setOverlays(d.overlays ?? []))
      .catch(() => setOverlays([]));
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
        setParetoData(null); // веса изменились — старый фронт неактуален
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
    setParetoData(null);
  }, []);

  // ---------- демо-сценарий в один клик (для показа жюри) ----------
  // Ищет свободную площадку 40×40 м в 60–500 м от первой теплосети
  // (не пересекает существующую застройку), ставит туда 9-этажку
  // и запускает трассировку. Работает на любых загруженных данных.
  const handleDemo = useCallback(() => {
    const layers = layersData?.layers;
    const bounds = layersData?.bounds;
    const network = layers?.heat_networks?.[0];
    if (!layers || !bounds || !network) {
      setError('Карта ещё не загрузилась');
      return;
    }
    const [x0, y0, x1, y1] = bounds;
    const buildings = layers.buildings ?? [];
    const half = 20;
    let best = null;
    for (let x = x0 + 80; x < x1 - 80; x += 50) {
      for (let y = y0 + 80; y < y1 - 80; y += 50) {
        if (buildings.some((b) => boxIntersectsPolygon(x, y, half + 5, b.coordinates))) continue;
        const dNet = distToPolyline(x, y, network.coordinates);
        if (dNet < 60 || dNet > 500) continue; // не вплотную к трубе и не через полкарты
        const score = Math.abs(dNet - 250);  // идеальная демо-дистанция ~250 м
        if (!best || score < best.score) best = { x, y, score };
      }
    }
    if (!best) {
      setError('Не нашлось свободной площадки рядом с теплосетью');
      return;
    }
    const { x: cx, y: cy } = best;
    const polygon = [
      [cx - half, cy - half],
      [cx + half, cy - half],
      [cx + half, cy + half],
      [cx - half, cy + half],
    ];
    const building = { polygon, floors: 9, center: [cx, cy] };
    setNewBuilding(building);
    setSelectedNetworkId(network.id);
    setRouteData(null);
    setValidation(null);
    setEditPath(null);
    setSavedId(null);
    setError(null);
    setMode('view');
    runRouting(building, network.id, turnPenalty, roadMult);
  }, [layersData, runRouting, turnPenalty, roadMult]);

  // ---------- обратная задача: сканирование площадок ----------
  const handleScan = useCallback(() => {
    setScanning(true);
    setSiteScan(null);
    setError(null);
    postScan(selectedNetworkId, buildingSize, floors)
      .then((data) => {
        setSiteScan(data);
        if (!data.top.length) {
          setError('Свободных площадок в 60–500 м от теплосети не нашлось');
        }
      })
      .catch((e) => setError(e.message))
      .finally(() => setScanning(false));
  }, [selectedNetworkId, buildingSize, floors]);

  // Клик по площадке в рейтинге: ставим туда здание и строим трассу.
  const handlePickSite = useCallback((site) => {
    const building = {
      polygon: site.polygon,
      floors: siteScan?.floors ?? floors,
      center: site.center,
    };
    const netId = siteScan?.network_id ?? selectedNetworkId;
    setNewBuilding(building);
    if (netId) setSelectedNetworkId(netId);
    setRouteData(null);
    setValidation(null);
    setEditPath(null);
    setSavedId(null);
    setError(null);
    setMode('view');
    if (netId) runRouting(building, netId, turnPenalty, roadMult);
  }, [siteScan, floors, selectedNetworkId, turnPenalty, roadMult, runRouting]);

  // ---------- загрузка произвольного района из OSM ----------
  const handleLoadDistrict = useCallback((payload) => {
    setDistrictLoading(true);
    setError(null);
    postLoadBbox(payload)
      .then(() => Promise.all([fetchLayers(), fetchTerrainMesh(), fetchNetworkStats(), fetchOverlays()]))
      .then(([layers, mesh, stats, ov]) => {
        setLayersData(layers);
        setMeshData(mesh);
        setNetStats(stats);
        setOverlays(ov.overlays ?? []); // те же слои, перепроецированные на новый район
        handleReset();
        setSiteScan(null);
      })
      .catch((e) => setError(e.message))
      .finally(() => setDistrictLoading(false));
  }, [handleReset]);

  // ---------- лидар: демо / загрузка / сброс ----------
  // После смены рельефа перечитываем меш — здания, дороги и трубы
  // сами пересадятся на новые высоты (эффект драпировки по meshData).
  const applyLidar = useCallback((promise) => {
    setLidarBusy(true);
    setError(null);
    promise
      .then((st) => {
        setLidarStatus(st);
        setShowCloud(Boolean(st?.active));
        return fetchTerrainMesh();
      })
      .then(setMeshData)
      .catch((e) => setError(e.message))
      .finally(() => setLidarBusy(false));
  }, []);

  const handleLidarDemo = useCallback(
    () => applyLidar(postLidarDemo()), [applyLidar]);
  const handleLidarUpload = useCallback(
    (file) => applyLidar(postLidarUpload(file)), [applyLidar]);
  const handleLidarClear = useCallback(() => {
    setShowCloud(false);
    applyLidar(postLidarClear());
  }, [applyLidar]);

  // ---------- парето-анализ ----------
  // Точки фронта подмешиваются в список вариантов фиолетовым —
  // дальше работает весь контур (3D, валидация, gizmo, сохранение).
  const handlePareto = useCallback(() => {
    if (!newBuilding || !selectedNetworkId) return;
    setParetoBusy(true);
    setError(null);
    postPareto(newBuilding.polygon, newBuilding.floors, selectedNetworkId)
      .then((data) => {
        setParetoData(data);
        setRouteData((prev) => {
          if (!prev) return prev;
          const existing = new Set(prev.variants.map((v) => v.key));
          const extra = data.points
            .filter((pt) => !existing.has(pt.key))
            .map((pt) => ({
              key: pt.key,
              name: `Парето ${pt.key.split('_')[1]}`,
              color: pt.is_pareto ? '#a55eea' : '#b2bec3',
              path: pt.path,
              length_m: pt.length_m,
              turns: pt.turns,
              params: pt.params,
            }));
          return { ...prev, variants: [...prev.variants, ...extra] };
        });
      })
      .catch((e) => setError(e.message))
      .finally(() => setParetoBusy(false));
  }, [newBuilding, selectedNetworkId]);

  // ---------- PDF-отчёт ----------
  const handleReportPdf = useCallback(() => {
    const path = currentPath();
    if (!path || !newBuilding || !selectedNetworkId) return;
    setPdfBusy(true);
    const variant = mode === 'editRoute' ? 'custom' : selectedRouteKey;
    postReportPdf(newBuilding.polygon, newBuilding.floors,
                  selectedNetworkId, path, variant)
      .then((blob) => {
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'heat_connection_report.pdf';
        a.click();
        URL.revokeObjectURL(url);
      })
      .catch((e) => setError(e.message))
      .finally(() => setPdfBusy(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, editPath, routeData, selectedRouteKey, newBuilding, selectedNetworkId]);

  // ---------- оверлеи: НСПД / data.mos.ru / GeoJSON ----------
  const refreshOverlays = useCallback(
    () => fetchOverlays()
      .then((d) => setOverlays(d.overlays ?? []))
      .catch(() => {}),
    [],
  );

  const handleNspd = useCallback((layerKeys) => {
    setOverlayBusy(true);
    setError(null);
    postNspdOverlay(layerKeys)
      .then(() => refreshOverlays())
      .catch((e) => setError(e.message))
      .finally(() => setOverlayBusy(false));
  }, [refreshOverlays]);

  const handleDatamos = useCallback((datasetId, apiKey, limit) => {
    setOverlayBusy(true);
    setError(null);
    postDatamosOverlay(datasetId, apiKey, limit)
      .then(() => refreshOverlays())
      .catch((e) => setError(e.message))
      .finally(() => setOverlayBusy(false));
  }, [refreshOverlays]);

  const handleGeojsonFile = useCallback((file) => {
    setOverlayBusy(true);
    setError(null);
    file.text()
      .then((text) => {
        const geojson = JSON.parse(text);
        const name = file.name.replace(/\.(geo)?json$/i, '');
        return postGeojsonOverlay(name, '#8a5cf6', geojson);
      })
      .then(() => refreshOverlays())
      .catch((e) => setError(`GeoJSON: ${e.message}`))
      .finally(() => setOverlayBusy(false));
  }, [refreshOverlays]);

  const handleOverlayDelete = useCallback((id) => {
    deleteOverlay(id)
      .then(() => {
        setHiddenOverlays((prev) => {
          const next = new Set(prev);
          next.delete(id);
          return next;
        });
        refreshOverlays();
      })
      .catch((e) => setError(e.message));
  }, [refreshOverlays]);

  const handleOverlayToggle = useCallback((id) => {
    setHiddenOverlays((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
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
        validation={validation}
        netStats={netStats}
        savedId={savedId}
        onStartEdit={handleStartEdit}
        onFinishEdit={handleFinishEdit}
        onSave={handleSave}
        onExport={() => exportSceneGLB()}
        error={error}
        onReset={handleReset}
        onDemo={handleDemo}
        backendOk={backendOk}
        siteScan={siteScan}
        scanning={scanning}
        onScan={handleScan}
        onPickSite={handlePickSite}
        xray={xray}
        onToggleXray={() => setXray((v) => !v)}
        presets={presets}
        districtLoading={districtLoading}
        onLoadDistrict={handleLoadDistrict}
        paretoData={paretoData}
        paretoBusy={paretoBusy}
        onPareto={handlePareto}
        pdfBusy={pdfBusy}
        onReportPdf={handleReportPdf}
        lidarStatus={lidarStatus}
        lidarBusy={lidarBusy}
        showCloud={showCloud}
        setShowCloud={setShowCloud}
        onLidarDemo={handleLidarDemo}
        onLidarUpload={handleLidarUpload}
        onLidarClear={handleLidarClear}
        overlays={overlays}
        hiddenOverlays={hiddenOverlays}
        overlayBusy={overlayBusy}
        onNspd={handleNspd}
        onDatamos={handleDatamos}
        onGeojsonFile={handleGeojsonFile}
        onOverlayDelete={handleOverlayDelete}
        onOverlayToggle={handleOverlayToggle}
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
        siteScan={siteScan}
        xray={xray}
        showCloud={showCloud && Boolean(lidarStatus?.active)}
        overlays={overlays}
        hiddenOverlays={hiddenOverlays}
      />
    </div>
  );
}
