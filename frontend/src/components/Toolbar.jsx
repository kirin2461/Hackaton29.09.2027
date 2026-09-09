// Панель инструментов.
import { useState } from 'react';
import ParetoChart from './ParetoChart.jsx';
// Спринт 2 — варианты трассы A*, бегунки штрафов.
// Спринт 3 — смета/гидравлика, редактирование трубы, сохранение.
// Спринт 4 — экспорт сцены в .glb.

export default function Toolbar({
  mode, setMode, floors, setFloors, buildingSize, setBuildingSize,
  networks, selectedNetworkId, onPickNetwork, routeData, routing,
  selectedRouteKey, onSelectRoute,
  turnPenalty, setTurnPenalty, roadMult, setRoadMult,
  validation, netStats, savedId, onStartEdit, onFinishEdit, onSave, onExport,
  error, onReset, onDemo, backendOk,
  siteScan, scanning, onScan, onPickSite,
  xray, onToggleXray,
  presets, districtLoading, onLoadDistrict,
  lidarStatus, lidarBusy, showCloud, setShowCloud,
  onLidarDemo, onLidarUpload, onLidarClear,
  paretoData, paretoBusy, onPareto, pdfBusy, onReportPdf,
}) {
  // Локальные поля произвольного bbox (градусы WGS84).
  const [bbox, setBbox] = useState({ min_lat: '', min_lon: '', max_lat: '', max_lon: '' });
  const bboxReady = ['min_lat', 'min_lon', 'max_lat', 'max_lon']
    .every((k) => bbox[k] !== '' && Number.isFinite(Number(bbox[k])));
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

      <div className="group">
        <h2>Обратная задача</h2>
        <button onClick={onScan} disabled={scanning}>
          {scanning ? '⏳ Сканирую квартал…' : '🔍 Топ-5 площадок под здание'}
        </button>
        {siteScan && (
          <>
            <p className="hint">
              Проверено {siteScan.scanned} участков, подходит {siteScan.viable}.
              Площадка {siteScan.building_size_m}×{siteScan.building_size_m} м,
              {' '}{siteScan.floors} эт.
            </p>
            <ul className="site-list">
              {siteScan.top.map((t) => (
                <li key={t.rank} onClick={() => onPickSite(t)}>
                  <b>#{t.rank}</b> {t.cost_mln_rub} млн ₽
                  <small>
                    {t.length_m} м · ΔH{' '}
                    {t.entropy_delta >= 0 ? '+' : ''}
                    {(t.entropy_delta * 100).toFixed(2)} п.п.
                  </small>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>

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

      {variants.length > 0 && mode !== 'editRoute' && (
        <div className="group">
          <h2>Парето: цена vs надёжность</h2>
          <button onClick={onPareto} disabled={paretoBusy}>
            {paretoBusy ? '⏳ Сканирую пространство весов…' : '⚖ Построить Парето-фронт'}
          </button>
          {paretoData && (
            <>
              <ParetoChart
                data={paretoData}
                selectedKey={selectedRouteKey}
                onSelect={onSelectRoute}
              />
              <p className="hint">
                Фиолетовые точки — недоминируемые варианты (фронт):
                дешевле — значит менее надёжно, и наоборот.
                Клик по точке выбирает трассу.
              </p>
            </>
          )}
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

      {(netStats || validation?.network) && (
        <div className="group result">
          <h2>Живучесть сети</h2>
          {netStats && (
            <>
              <p>Сегментов: {netStats.edges}, узлов: {netStats.nodes}</p>
              <p>Равномерность (энтропия): {netStats.entropy_norm}</p>
              <p>Связность (Фидлер): {netStats.fiedler.toExponential(2)}</p>
              <p>Кольца: {netStats.loops} · тупиков: {netStats.dead_ends}</p>
            </>
          )}
          {validation?.network && (
            <>
              <p className="impact">
                После врезки: энтропия {validation.network.after.entropy_norm}{' '}
                ({validation.network.delta.entropy_norm >= 0 ? '+' : ''}
                {(validation.network.delta.entropy_norm * 100).toFixed(2)} п.п.)
              </p>
              <p className="impact">
                Фидлер: {validation.network.after.fiedler.toExponential(2)}{' '}
                ({validation.network.delta.fiedler >= 0 ? '+' : '−'}
                {netStats && netStats.fiedler > 0
                  ? Math.abs(validation.network.delta.fiedler / netStats.fiedler * 100).toFixed(1)
                  : '—'}%)
              </p>
            </>
          )}
          {validation?.reliability && (
            <>
              <p className="impact">
                N-1 (худший отказ): {validation.reliability.before.n1_worst_pct}% →{' '}
                {validation.reliability.after.n1_worst_pct}% тепла без подачи
              </p>
              <p className="impact">
                Монте-Карло ({validation.reliability.before.mc_trials} сценариев, p=
                {validation.reliability.before.fail_prob}):{' '}
                {validation.reliability.before.mc_unserved_pct}% →{' '}
                {validation.reliability.after.mc_unserved_pct}%
              </p>
            </>
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
          <button onClick={onReportPdf} disabled={pdfBusy}>
            {pdfBusy ? '⏳ Собираю PDF…' : '📄 PDF-отчёт'}
          </button>
          {savedId && <p className="status ok">Сохранено: {savedId}</p>}
        </div>
      )}

      {error && <p className="error">{error}</p>}

      <div className="group">
        <button className={xray ? 'active' : ''} onClick={onToggleXray}>
          {xray ? '🩻 Рентген: ВКЛ' : '🩻 Рентген (подземные сети)'}
        </button>
        {xray && (
          <p className="hint">
            Земля полупрозрачная: существующие трубы на глубине −2 м,
            новая трасса — −3 м. Камера может опускаться ниже горизонта.
          </p>
        )}
      </div>

      <div className="group">
        <h2>Лидар (LAS/LAZ)</h2>
        {lidarStatus?.active ? (
          <>
            <p className="hint">
              {lidarStatus.source}: {lidarStatus.points_total.toLocaleString('ru')} точек
              (земля: {lidarStatus.points_ground.toLocaleString('ru')}),
              перепад {lidarStatus.z_range_m} м
            </p>
            <button
              className={showCloud ? 'active' : ''}
              onClick={() => setShowCloud((v) => !v)}
            >
              {showCloud ? '☁ Облако точек: ВКЛ' : '☁ Облако точек'}
            </button>
            <button onClick={onLidarClear} disabled={lidarBusy}>
              ↩ Вернуть демо-рельеф
            </button>
          </>
        ) : (
          <>
            <button onClick={onLidarDemo} disabled={lidarBusy}>
              {lidarBusy ? '⏳ Обработка облака…' : '⚡ Демо-лидар (1,8 млн точек)'}
            </button>
            <label className="file-label">
              …или свой .las/.laz:
              <input
                type="file"
                accept=".las,.laz"
                disabled={lidarBusy}
                onChange={(e) => e.target.files[0] && onLidarUpload(e.target.files[0])}
              />
            </label>
          </>
        )}
      </div>

      <div className="group">
        <h2>Район (OpenStreetMap)</h2>
        {presets.length > 0 && (
          <div className="preset-grid">
            {presets.map((pr) => (
              <button
                key={pr.key}
                disabled={districtLoading}
                onClick={() => onLoadDistrict({ preset: pr.key })}
              >
                {pr.key}
              </button>
            ))}
          </div>
        )}
        <div className="bbox-grid">
          {['min_lat', 'min_lon', 'max_lat', 'max_lon'].map((k) => (
            <input
              key={k}
              placeholder={k}
              value={bbox[k]}
              onChange={(e) => setBbox({ ...bbox, [k]: e.target.value })}
            />
          ))}
        </div>
        <button
          disabled={!bboxReady || districtLoading}
          onClick={() => onLoadDistrict({
            min_lat: Number(bbox.min_lat),
            min_lon: Number(bbox.min_lon),
            max_lat: Number(bbox.max_lat),
            max_lon: Number(bbox.max_lon),
          })}
        >
          {districtLoading ? '⏳ Загружаю из OSM…' : '⤓ Загрузить свой bbox'}
        </button>
        {districtLoading && (
          <p className="hint">Overpass API собирает геометрию — до минуты.</p>
        )}
      </div>

      <button className="demo" onClick={onDemo}>▶ Демо-сценарий</button>
      <button className="reset" onClick={onReset}>Сбросить проект</button>
    </aside>
  );
}
