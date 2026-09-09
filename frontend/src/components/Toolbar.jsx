// Панель инструментов.
// День 5 — интерфейс «Точка посадки»; Спринт 2 — варианты трассы A*,
// бегунки штрафов (штраф за поворот / проход по дорогам).

export default function Toolbar({
  mode, setMode, floors, setFloors, buildingSize, setBuildingSize,
  networks, selectedNetworkId, onPickNetwork, routeData, routing,
  selectedRouteKey, onSelectRoute,
  turnPenalty, setTurnPenalty, roadMult, setRoadMult,
  error, onReset, backendOk,
}) {
  const variants = routeData?.variants ?? [];

  return (
    <aside className="toolbar">
      <h1>Теплосети 3D</h1>
      <p className={`status ${backendOk ? 'ok' : 'bad'}`}>
        Backend: {backendOk === null ? 'проверка…' : backendOk ? 'подключён' : 'недоступен'}
      </p>

      <div className="group">
        <button
          className={mode === 'view' ? 'active' : ''}
          onClick={() => setMode('view')}
        >
          Обзор
        </button>
        <button
          className={mode === 'addBuilding' ? 'active' : ''}
          onClick={() => setMode('addBuilding')}
        >
          + Здание (Точка Б)
        </button>
        <button
          className={mode === 'selectNetwork' ? 'active' : ''}
          onClick={() => setMode('selectNetwork')}
        >
          ⌁ Теплосеть (Точка А)
        </button>
      </div>

      {mode === 'addBuilding' && (
        <div className="group">
          <label>
            Этажность: {floors}
            <input
              type="range" min="1" max="25" value={floors}
              onChange={(e) => setFloors(Number(e.target.value))}
            />
          </label>
          <label>
            Сторона здания: {buildingSize} м
            <input
              type="range" min="15" max="80" step="5" value={buildingSize}
              onChange={(e) => setBuildingSize(Number(e.target.value))}
            />
          </label>
          <p className="hint">Кликните по рельефу — там появится новое здание.</p>
        </div>
      )}

      {mode === 'selectNetwork' && (
        <div className="group">
          <p className="hint">Кликните по красной линии теплосети на карте.</p>
          <ul className="network-list">
            {networks.map((n) => (
              <li
                key={n.id}
                className={n.id === selectedNetworkId ? 'selected' : ''}
                onClick={() => onPickNetwork(n.id)}
              >
                {n.properties?.name || n.id}
              </li>
            ))}
          </ul>
        </div>
      )}

      {routing && <p className="status">Расчёт трассы…</p>}

      {variants.length > 0 && (
        <div className="group">
          <h2>Варианты трассы (A*)</h2>
          {variants.map((v) => (
            <div
              key={v.key}
              className={`variant ${v.key === selectedRouteKey ? 'selected' : ''}`}
              onClick={() => onSelectRoute(v.key)}
            >
              <span className="swatch" style={{ background: v.color }} />
              <div className="variant-body">
                <b>{v.name}</b>
                <small>
                  {v.length_m} м · поворотов: {v.turns}
                </small>
              </div>
            </div>
          ))}
          <p className="hint">Клик по варианту или по трубе на карте — выбрать.</p>
        </div>
      )}

      {variants.length > 0 && (
        <div className="group">
          <h2>Подгонка трассы</h2>
          <label>
            Штраф за поворот: {turnPenalty} м/45°
            <input
              type="range" min="0" max="10" step="0.5" value={turnPenalty}
              onChange={(e) => setTurnPenalty(Number(e.target.value))}
            />
          </label>
          <label>
            Проход по дорогам: ×{roadMult}
            <input
              type="range" min="1" max="20" step="1" value={roadMult}
              onChange={(e) => setRoadMult(Number(e.target.value))}
            />
          </label>
        </div>
      )}

      {routeData?.building && (
        <div className="group result">
          <h2>Расчёт подключения</h2>
          <p>Площадь: {routeData.building.area_m2} м²</p>
          <p>Нагрузка: {routeData.building.heat_load_kw} кВт</p>
          <p>По прямой до сети: {routeData.connection.length_m} м</p>
        </div>
      )}

      {error && <p className="error">{error}</p>}

      <button className="reset" onClick={onReset}>Сбросить проект</button>
    </aside>
  );
}
