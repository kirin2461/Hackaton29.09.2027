// Панель инструментов (День 5 — интерфейс «Точка посадки»).
// Три режима: обзор, добавление здания (Точка Б), выбор теплосети (Точка А).

export default function Toolbar({
  mode, setMode, floors, setFloors, buildingSize, setBuildingSize,
  networks, selectedNetworkId, result, error, onReset, backendOk,
}) {
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
                onClick={() => {}}
              >
                {n.properties?.name || n.id}
              </li>
            ))}
          </ul>
        </div>
      )}

      {result && (
        <div className="group result">
          <h2>Расчёт врезки</h2>
          <p>Площадь: {result.building.area_m2} м²</p>
          <p>Нагрузка: {result.building.heat_load_kw} кВт</p>
          <p>Длина подключения: {result.connection.length_m} м</p>
        </div>
      )}

      {error && <p className="error">{error}</p>}

      <button className="reset" onClick={onReset}>Сбросить проект</button>
    </aside>
  );
}
