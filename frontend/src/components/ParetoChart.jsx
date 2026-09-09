// Парето-фронт «цена ↔ надёжность сети» — мини-график на чистом SVG.
// Каждая точка — уникальная трасса из сканирования весов A*.
// Фиолетовые — недоминируемые (фронт), серые — доминируемые.
// Клик по точке выбирает её трассу в основном контуре.

const W = 252;
const H = 190;
const ML = 44; // отступы: лево/право/верх/низ
const MR = 10;
const MT = 12;
const MB = 36;

export default function ParetoChart({ data, selectedKey, onSelect }) {
  if (!data?.points?.length) return null;
  const xs = data.points.map((p) => p.cost_mln_rub);
  const ys = data.points.map((p) => p.n1_after_pct);
  const x0 = Math.min(...xs);
  const x1 = Math.max(...xs);
  const y0 = Math.min(...ys);
  const y1 = Math.max(...ys);
  const padX = Math.max((x1 - x0) * 0.12, 0.5);
  const padY = Math.max((y1 - y0) * 0.15, 0.05);

  const sx = (v) => ML + ((v - (x0 - padX)) / Math.max(x1 - x0 + 2 * padX, 1e-9)) * (W - ML - MR);
  const sy = (v) => H - MB - ((v - (y0 - padY)) / Math.max(y1 - y0 + 2 * padY, 1e-9)) * (H - MT - MB);

  const front = data.points
    .filter((p) => p.is_pareto)
    .sort((a, b) => a.cost_mln_rub - b.cost_mln_rub);

  return (
    <svg className="pareto-chart" viewBox={`0 0 ${W} ${H}`}>
      {/* оси */}
      <line x1={ML} y1={MT} x2={ML} y2={H - MB} className="axis" />
      <line x1={ML} y1={H - MB} x2={W - MR} y2={H - MB} className="axis" />
      <text x={W / 2} y={H - 6} className="axis-label" textAnchor="middle">
        {data.x_axis.name}
      </text>
      <text
        x={12} y={H / 2} className="axis-label" textAnchor="middle"
        transform={`rotate(-90 12 ${H / 2})`}
      >
        N-1, %
      </text>
      {/* линия фронта */}
      {front.length > 1 && (
        <polyline
          points={front.map((p) => `${sx(p.cost_mln_rub)},${sy(p.n1_after_pct)}`).join(' ')}
          className="pareto-front"
        />
      )}
      {/* точки */}
      {data.points.map((p) => (
        <circle
          key={p.key}
          cx={sx(p.cost_mln_rub)}
          cy={sy(p.n1_after_pct)}
          r={p.key === selectedKey ? 7 : 5}
          className={[
            'pareto-dot',
            p.is_pareto ? 'front' : 'dominated',
            p.key === selectedKey ? 'selected' : '',
          ].join(' ')}
          onClick={() => onSelect(p.key)}
        >
          <title>
            {`${p.cost_mln_rub} млн ₽ · N-1 ${p.n1_after_pct}% · ${p.length_m} м · поворотов ${p.turns}`}
          </title>
        </circle>
      ))}
    </svg>
  );
}
