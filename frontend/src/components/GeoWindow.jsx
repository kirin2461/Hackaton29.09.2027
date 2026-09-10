// Нижнее плавающее окно: геодезия (рулетка) и сведения о грунте
// (отметка, уклон, экспозиция — из ЦМР: демо-рельеф или лидар).

export default function GeoWindow({ measurePoints, soil, onMeasureClear, onClose }) {
  const hasMeasure = measurePoints?.length > 0;
  if (!hasMeasure && !soil) return null;

  const segs = (measurePoints ?? []).slice(1).map((pt, i) => {
    const [ax, ay] = measurePoints[i];
    return Math.hypot(pt[0] - ax, pt[1] - ay);
  });
  const total = segs.reduce((a, b) => a + b, 0);
  const aspectText = (deg) => {
    if (deg == null) return '—';
    const dirs = ['С', 'СВ', 'В', 'ЮВ', 'Ю', 'ЮЗ', 'З', 'СЗ'];
    return `${dirs[Math.round(deg / 45) % 8]} (${deg}°)`;
  };

  return (
    <div className="float-window float-bottom">
      <button className="float-close" onClick={onClose} title="Закрыть">✕</button>
      {hasMeasure && (
        <div className="geo-block">
          <h2>Геодезия</h2>
          <div className="geo-row">
            <span>Точек: {measurePoints.length}</span>
            <span>
              Пролёты: {segs.map((d) => d.toFixed(1)).join(' + ') || '—'} м
            </span>
            <b>Σ {total.toFixed(1)} м</b>
            <button onClick={onMeasureClear}>Очистить</button>
          </div>
        </div>
      )}
      {soil && (
        <div className="geo-block">
          <h2>Грунт (по ЦМР{soil.source === 'lidar' ? ' — лидар' : ''})</h2>
          <div className="geo-row">
            <span>Отметка: <b>{soil.ground_z_m} м</b></span>
            <span>Уклон: <b>{soil.slope_pct}%</b></span>
            <span>Экспозиция: <b>{aspectText(soil.aspect_deg)}</b></span>
            <span className="geo-coord">({soil.x.toFixed(0)}; {soil.y.toFixed(0)})</span>
          </div>
        </div>
      )}
    </div>
  );
}
