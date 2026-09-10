// Панель инструментов.
import { useState } from 'react';
import ParetoChart from './ParetoChart.jsx';
import RouteProfile from './RouteProfile.jsx';
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
  overlays, hiddenOverlays, overlayBusy, onNspd, onDatamos,
  onGeojsonFile, onOverlayDelete, onOverlayToggle,
  measurePoints, onMeasureClear, passport, onConnectObject,
  profile, freeCamera, onToggleFreeCamera, nspdBrowserBusy, onNspdBrowser,
}) {
  // Локальные поля произвольного bbox (градусы WGS84).
  const [bbox, setBbox] = useState({ min_lat: '', min_lon: '', max_lat: '', max_lon: '' });
  const bboxReady = ['min_lat', 'min_lon', 'max_lat', 'max_lon']
    .every((k) => bbox[k] !== '' && Number.isFinite(Number(bbox[k])));
  const variants = routeData?.variants ?? [];
  // Поля коннектора data.mos.ru (номер набора + бесплатный ключ).
  const [dmDataset, setDmDataset] = useState('');
  const [dmKey, setDmKey] = useState('');
  const dmReady = dmDataset.trim() !== '' && dmKey.trim() !== '';
  // Рулетка: длина ломаной и длины сегментов.
  const measureSegs = (measurePoints ?? []).slice(1).map((pt, i) => {
    const [ax, ay] = measurePoints[i];
    return Math.hypot(pt[0] - ax, pt[1] - ay);
  });
  const measureTotal = measureSegs.reduce((a, b) => a + b, 0);
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
        <button
          className={mode === 'object' ? 'active' : ''}
          onClick={() => setMode('object')}
        >
          🛈 Объект (паспорт)
        </button>
        <button
          className={mode === 'measure' ? 'active' : ''}
          onClick={() => setMode('measure')}
        >
          📐 Измерение
        </button>
      </div>

      <div className="group">
        <button
          className={freeCamera ? 'active' : ''}
          onClick={onToggleFreeCamera}
        >
          {freeCamera ? '🕹 Свободная камера: ВКЛ' : '🕹 Свободная камера'}
        </button>
        {freeCamera && (
          <p className="hint">
            Карта двигается без закреплённой точки: WASD / стрелки —
            полёт, правая кнопка мыши — панорама, колесо — зум.
            Наклон не ограничен.
          </p>
        )}
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

      {mode === 'measure' && (
        <div className="group result">
          <h2>Геодезия (рулетка)</h2>
          <p className="hint">Кликайте по карте — точки соединяются в ломаную.</p>
          {measurePoints.length > 0 && (
            <>
              <p>Точек: {measurePoints.length}</p>
              {measureSegs.map((d, i) => (
                <p key={i}>Пролёт {i + 1}: {d.toFixed(1)} м</p>
              ))}
              <p className="cost">Σ {measureTotal.toFixed(1)} м</p>
              <button onClick={onMeasureClear}>Очистить</button>
            </>
          )}
        </div>
      )}

      {passport && (
        <div className="group result">
          <h2>Паспорт объекта</h2>
          <p><b>{passport.name}</b></p>
          <p>Этажность: {passport.floors} · площадь: {passport.area_m2} м²</p>
          <p>Отметка земли: {passport.ground_z_m} м</p>
          <p>Расчётная тепловая нагрузка: {passport.heat_load_kw} кВт</p>
          {passport.network && (
            <>
              <h2>Коммуникации</h2>
              <p className="impact">
                Ближайшая теплосеть: {passport.network.name} —{' '}
                {passport.network.distance_m} м
              </p>
            </>
          )}
          {passport.roads.length > 0 && (
            <p>Дороги рядом: {passport.roads.map((r) => r.name).join(', ')}</p>
          )}
          {passport.zones.length > 0 && (
            <p className="error">⚠ Охранные зоны: {passport.zones.join('; ')}</p>
          )}
          {passport.network && (
            <button onClick={onConnectObject}>
              ⌁ Проложить трассу к этому объекту
            </button>
          )}
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

      {profile && (
        <div className="group result">
          <h2>Профиль трассы (разрез)</h2>
          <RouteProfile profile={profile} />
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

      <div className="group">
        <h2>Источники (всё в одну карту)</h2>
        <button
          disabled={nspdBrowserBusy}
          title="Запрос уходит из вашего браузера — домашний IP не блокируется Qrator"
          onClick={() => onNspdBrowser(['nspd_zdaniya', 'nspd_sooruzheniya', 'nspd_zouit'])}
        >
          {nspdBrowserBusy ? '⏳ Запрашиваю НСПД из браузера…'
            : '🏛 НСПД (ЕГРН): здания, сооружения, ЗОУИТ'}
        </button>
        <button
          disabled={overlayBusy}
          title="Серверный запрос — с боевого сервера Qrator обычно блокирует"
          onClick={() => onNspd(['nspd_zdaniya', 'nspd_sooruzheniya', 'nspd_zouit'])}
        >
          {overlayBusy ? '⏳ Загружаю…' : '🏛 НСПД через сервер'}
        </button>
        <p className="hint">
          Обход блокировки: первая кнопка шлёт запрос прямо из браузера
          (Qrator блокирует IP дата-центров, но не домашние). Если и это
          не помогло — выгрузите GeoJSON с nspd.gov.ru и загрузите ниже.
        </p>
        <div className="bbox-grid">
          <input
            placeholder="ID набора"
            value={dmDataset}
            onChange={(e) => setDmDataset(e.target.value)}
          />
          <input
            placeholder="api_key data.mos.ru"
            value={dmKey}
            onChange={(e) => setDmKey(e.target.value)}
          />
        </div>
        <button
          disabled={!dmReady || overlayBusy}
          onClick={() => onDatamos(Number(dmDataset), dmKey.trim(), 500)}
        >
          ⤓ data.mos.ru на карту
        </button>
        <label className="file-label">
          …или свой GeoJSON (EPSG:4326):
          <input
            type="file"
            accept=".json,.geojson"
            disabled={overlayBusy}
            onChange={(e) => e.target.files[0] && onGeojsonFile(e.target.files[0])}
          />
        </label>
        {overlays.length > 0 && (
          <ul className="overlay-list">
            {overlays.map((ov) => (
              <li key={ov.id}>
                <input
                  type="checkbox"
                  checked={!hiddenOverlays.has(ov.id)}
                  onChange={() => onOverlayToggle(ov.id)}
                />
                <span className="swatch" style={{ background: ov.color }} />
                <span className="overlay-name" title={ov.name}>
                  {ov.name} <small>({ov.count})</small>
                </span>
                <button
                  className="overlay-del"
                  title="Удалить слой"
                  onClick={() => onOverlayDelete(ov.id)}
                >
                  ✕
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <button className="demo" onClick={onDemo}>▶ Демо-сценарий</button>
      <button className="reset" onClick={onReset}>Сбросить проект</button>
    </aside>
  );
}
