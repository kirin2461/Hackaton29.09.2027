// Панель инструментов.
// Спринт 2 — варианты трассы A*, бегунки штрафов.
// Спринт 3 — смета/гидравлика, редактирование трубы, сохранение.
// Спринт 4 — экспорт сцены в .glb.

export default function Toolbar({
  mode, setMode, floors, setFloors, buildingSize, setBuildingSize,
  networks, selectedNetworkId, onPickNetwork, routeData, routing,
  selectedRouteKey, onSelectRoute,
  turnPenalty, setTurnPenalty, roadMult, setRoadMult,
  validation, savedId, onStartEdit, onFinishEdit, onSave, onExport,
  error, onReset, onDemo, backendOk,
}) {
  const variants = routeData?.variants ?? [];
  const collision = Boolean(validation?.collision);

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
          <p className="hint">Кликните по красной трубе на карте или по имени:</p>
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
          {mode === 'editRoute' ? (
            <>
              <button onClick={onFinishEdit}>✓ Закончить правку</button>
              <p className="hint">
                Кликните по оранжевому узлу и тяните — труба и смета
                пересчитаются на лету.
              </p>
            </>
          ) : (
            <button onClick={onStartEdit}>✎ Редактировать трассу</button>
          )}
        </div>
      )}

      {variants.length > 0 && mode !== 'editRoute' && (
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

      {validation && (
        <div className="group result">
          <h2>Смета и гидравлика</h2>
          <p>Длина: {validation.length_m} м</p>
          <p>Поворотов: {validation.turns}</p>
          <p>Переходов под дорогами: {validation.road_crossings}</p>
          <p>Теплопотери: {validation.heat_loss_kw} кВт</p>
          <p className="cost">Стоимость: {validation.cost_mln_rub} млн ₽</p>
          {collision && (
            <p className="error">
              ⚠ Трасса пересекает здания: {validation.collision_buildings.join(', ')}
            </p>
          )}
        </div>
      )}

      {routeData?.building && (
        <div className="group result">
          <h2>Подключение</h2>
          <p>Площадь: {routeData.building.area_m2} м²</p>
          <p>Нагрузка: {routeData.building.heat_load_kw} кВт</p>
          {routeData.placement?.collision && (
            <p className="error">
              ⚠ Новое здание пересекается с существующими:{' '}
              {routeData.placement.buildings.join(', ')}. Переместите его на
              свободное место.
            </p>
          )}
        </div>
      )}

      {variants.length > 0 && (
        <div className="group">
          <button
            className="save"
            onClick={onSave}
            disabled={collision || routeData?.placement?.collision}
            title={
              collision
                ? 'Сначала исправьте коллизию'
                : routeData?.placement?.collision
                  ? 'Здание пересекается с существующей застройкой'
                  : ''
            }
          >
            💾 Сохранить проект
          </button>
          <button onClick={onExport}>⤓ Экспорт сцены (.glb)</button>
          {savedId && <p className="status ok">Сохранено: {savedId}</p>}
        </div>
      )}

      {error && <p className="error">{error}</p>}

      <button className="demo" onClick={onDemo}>▶ Демо-сценарий</button>
      <button className="reset" onClick={onReset}>Сбросить проект</button>
    </aside>
  );
}
