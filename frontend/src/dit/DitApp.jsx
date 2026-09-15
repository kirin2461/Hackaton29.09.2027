// Страница ДИТ (/dit): загрузка конкурсного GeoJSON → задание →
// варианты трассировки на карте + таблицы стоимости/диаметров/реконструкции.
// Работает ТОЛЬКО с Java API (Спринт 3): POST/GET /api/jobs.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import './dit.css';

// ---------- API (Java, :8080 — тот же origin в проде) ----------

async function apiUpload(file) {
  const form = new FormData();
  form.append('file', file);
  const res = await fetch('/api/jobs', { method: 'POST', body: form });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

async function apiJob(id) {
  const res = await fetch(`/api/jobs/${id}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

async function apiResult(id) {
  const res = await fetch(`/api/jobs/${id}/result`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

const STATUS_RU = {
  QUEUED: 'В очереди',
  PROCESSING: 'Расчёт…',
  DONE: 'Готово',
  PARTIAL: 'Частичный результат',
  FAILED: 'Ошибка',
};

// ---------- Главный компонент ----------

export default function DitApp() {
  const [job, setJob] = useState(null);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [selected, setSelected] = useState(1);
  const timer = useRef(null);

  const stopPolling = () => { if (timer.current) { clearInterval(timer.current); timer.current = null; } };
  useEffect(() => stopPolling, []);

  const onFile = useCallback(async (file) => {
    if (!file) return;
    stopPolling();
    setError(null); setResult(null); setJob(null); setSelected(1);
    try {
      const created = await apiUpload(file);
      setJob(created);
      timer.current = setInterval(async () => {
        try {
          const fresh = await apiJob(created.id);
          setJob(fresh);
          if (fresh.status === 'DONE' || fresh.status === 'PARTIAL' || fresh.status === 'FAILED') {
            stopPolling();
            if (fresh.status !== 'FAILED') {
              setResult(await apiResult(created.id));
            }
          }
        } catch (e) { stopPolling(); setError(e.message); }
      }, 2000);
    } catch (e) { setError(e.message); }
  }, []);

  const variants = result?.metadata?.variants ?? [];
  const active = variants.find((v) => v.rank === selected) ?? variants[0];

  return (
    <div className="dit">
      <header className="dit-header">
        <h1>Трассировка теплосетей · ДИТ</h1>
        <p>Загрузите совмещённый GeoJSON — сервис построит до трёх вариантов
          подключения перспективных ОКС и отранжирует их (70% стоимость + 30% длина).</p>
      </header>

      <UploadZone onFile={onFile} busy={!!job && !result && !error} />

      {job && <JobCard job={job} />}
      {error && <div className="dit-error">Ошибка: {error}</div>}

      {result && (
        <>
          <VariantTabs variants={variants} selected={active?.rank} onSelect={setSelected} />
          <div className="dit-main">
            <ResultMap result={result} variantRank={active?.rank} />
            <div className="dit-side">
              <CostTable variant={active} />
              <SegmentsTable result={result} variantRank={active?.rank} />
              <ReconTable result={result} variantRank={active?.rank} />
              <Warnings result={result} />
              <a className="dit-download" href={`/api/jobs/${job.id}/result`} download>
                ⬇ Скачать выходной GeoJSON
              </a>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

// ---------- Загрузка ----------

function UploadZone({ onFile, busy }) {
  const [drag, setDrag] = useState(false);
  return (
    <label
      className={`dit-upload ${drag ? 'drag' : ''}`}
      onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => { e.preventDefault(); setDrag(false); onFile(e.dataTransfer.files?.[0]); }}
    >
      <input type="file" accept=".geojson,.json" hidden disabled={busy}
        onChange={(e) => onFile(e.target.files?.[0])} />
      <span>{busy ? '⏳ Идёт расчёт…' : '📄 Выберите или перетащите GeoJSON (до 3 ГБ)'}</span>
    </label>
  );
}

function JobCard({ job }) {
  return (
    <div className={`dit-job status-${job.status.toLowerCase()}`}>
      <span className="dit-job-name">{job.filename}</span>
      <span className="dit-job-status">{STATUS_RU[job.status] ?? job.status}</span>
      {job.errorMessage && <span className="dit-job-err">{job.errorMessage}</span>}
    </div>
  );
}

// ---------- Вкладки вариантов ----------

function VariantTabs({ variants, selected, onSelect }) {
  return (
    <div className="dit-tabs">
      {variants.map((v) => (
        <button key={v.rank}
          className={`dit-tab ${v.rank === selected ? 'active' : ''}`}
          onClick={() => onSelect(v.rank)}>
          <b>#{v.rank}</b> {v.label}
          <small>{(v.costs_rub.total / 1e6).toFixed(1)} млн ₽ · {v.length_total_m} м
            {v.is_recommended ? ' · ★ рекомендуемый' : ''}</small>
        </button>
      ))}
    </div>
  );
}

// ---------- Карта (SVG, проекция lon/lat → экран) ----------

const COLORS = {
  trunk: '#00b894',
  branch: '#0984e3',
  special_passage: '#a55eea',
  new_chamber: '#00cec9',
  tapping: '#fdcb6e',
  technical_node: '#dfe6e9',
  reconstruction: '#e17055',
  unconnected: '#d63031',
};

function ResultMap({ result, variantRank }) {
  const feats = useMemo(
    () => result.features.filter((f) => f.properties.variant === variantRank),
    [result, variantRank]);

  const proj = useMemo(() => {
    const xs = [], ys = [];
    for (const f of feats) {
      const g = f.geometry;
      const pts = g.type === 'Point' ? [g.coordinates] : g.coordinates;
      for (const [x, y] of pts) { xs.push(x); ys.push(y); }
    }
    if (!xs.length) return null;
    const minX = Math.min(...xs), maxX = Math.max(...xs);
    const minY = Math.min(...ys), maxY = Math.max(...ys);
    const latMid = (minY + maxY) / 2;
    const kx = Math.cos((latMid * Math.PI) / 180); // учёт сжатия долготы
    const W = 880, H = 560, P = 30;
    const spanX = (maxX - minX) * kx || 1e-9;
    const spanY = (maxY - minY) || 1e-9;
    const s = Math.min((W - 2 * P) / spanX, (H - 2 * P) / spanY);
    return ([x, y]) => [P + (x - minX) * kx * s, H - P - (y - minY) * s];
  }, [feats]);

  if (!proj) return <div className="dit-map empty">Нет геометрии для отображения</div>;

  const path = (coords) => coords.map((p, i) => {
    const [sx, sy] = proj(p);
    return `${i ? 'L' : 'M'}${sx.toFixed(1)},${sy.toFixed(1)}`;
  }).join(' ');

  const dot = (p) => proj(p);

  return (
    <svg className="dit-map" viewBox="0 0 880 560">
      {feats.filter((f) => f.properties.object_type === 'reconstruction_segment').map((f, i) => (
        <path key={`r${i}`} d={path(f.geometry.coordinates)}
          stroke={COLORS.reconstruction} strokeWidth="4" fill="none"
          strokeDasharray="8 5" opacity="0.85">
          <title>Реконструкция {f.properties.object_id}: Ду{f.properties.existing_diameter_mm}
            → Ду{f.properties.required_diameter_mm}</title>
        </path>
      ))}
      {feats.filter((f) => f.properties.object_type === 'new_segment').map((f, i) => {
        const p = f.properties;
        const special = p.method === 'special_passage';
        return (
          <path key={`s${i}`} d={path(f.geometry.coordinates)}
            stroke={special ? COLORS.special_passage : COLORS[p.role] ?? COLORS.branch}
            strokeWidth={1.5 + p.diameter_mm / 120} fill="none"
            strokeDasharray={special ? '6 4' : undefined} strokeLinecap="round">
            <title>{p.object_id} · Ду{p.diameter_mm} · {p.flow_tph} т/ч · {p.length_m} м
              {special ? ' · спецпроход' : ''}</title>
          </path>
        );
      })}
      {feats.filter((f) => f.geometry.type === 'Point').map((f, i) => {
        const [sx, sy] = dot(f.geometry.coordinates);
        const p = f.properties;
        if (p.object_type === 'new_chamber') {
          return <circle key={i} cx={sx} cy={sy} r="7" fill={COLORS.new_chamber} stroke="#013" strokeWidth="1.5">
            <title>{p.object_id} ({p.kind})</title></circle>;
        }
        if (p.object_type === 'tapping') {
          return <rect key={i} x={sx - 6} y={sy - 6} width="12" height="12"
            fill={COLORS.tapping} transform={`rotate(45 ${sx} ${sy})`}>
            <title>Врезка в камеру {p.chamber_id}</title></rect>;
        }
        if (p.object_type === 'technical_node') {
          return <rect key={i} x={sx - 5} y={sy - 5} width="10" height="10"
            fill="none" stroke={COLORS.technical_node} strokeWidth="2">
            <title>{p.object_id}: {p.reason}</title></rect>;
        }
        if (p.object_type === 'unconnected') {
          return <g key={i} stroke={COLORS.unconnected} strokeWidth="3">
            <line x1={sx - 7} y1={sy - 7} x2={sx + 7} y2={sy + 7} />
            <line x1={sx - 7} y1={sy + 7} x2={sx + 7} y2={sy - 7} />
            <title>Не подключён: {p.building_id} — {p.reason}</title>
          </g>;
        }
        return null;
      })}
      <Legend />
    </svg>
  );
}

function Legend() {
  const items = [
    ['ствол', COLORS.trunk], ['ветвь', COLORS.branch],
    ['спецпроход', COLORS.special_passage], ['камера', COLORS.new_chamber],
    ['врезка', COLORS.tapping], ['реконструкция', COLORS.reconstruction],
    ['не подключён', COLORS.unconnected],
  ];
  return (
    <g className="dit-legend" transform="translate(12,12)">
      {items.map(([name, color], i) => (
        <g key={name} transform={`translate(0,${i * 20})`}>
          <rect width="12" height="12" fill={color} rx="2" />
          <text x="18" y="11">{name}</text>
        </g>
      ))}
    </g>
  );
}

// ---------- Таблицы ----------

function CostTable({ variant }) {
  if (!variant) return null;
  const c = variant.costs_rub;
  const rows = [
    ['Новые участки', c.new_segments],
    ['Новые камеры', c.new_chambers],
    ['Врезки', c.tappings],
    ['Реконструкция', c.reconstruction],
    ['Штраф за неподключённые', c.unconnected_penalty],
  ];
  return (
    <section className="dit-card">
      <h3>Калькуляция · score {variant.score}</h3>
      <table>
        <tbody>
          {rows.map(([name, val]) => (
            <tr key={name}><td>{name}</td><td className="num">{(val / 1e6).toFixed(2)}</td></tr>
          ))}
          <tr className="total"><td>ИТОГО</td><td className="num">{(c.total / 1e6).toFixed(2)}</td></tr>
        </tbody>
      </table>
      <p className="dit-note">млн ₽ · протяжённость {variant.length_total_m} м ·
        статус: {STATUS_RU[variant.status?.toUpperCase()] ?? variant.status}</p>
    </section>
  );
}

function SegmentsTable({ result, variantRank }) {
  const segs = result.features.filter(
    (f) => f.properties.variant === variantRank && f.properties.object_type === 'new_segment');
  if (!segs.length) return null;
  return (
    <section className="dit-card">
      <h3>Новые участки ({segs.length})</h3>
      <table>
        <thead><tr><th>ID</th><th>Роль</th><th>Ду, мм</th><th>Расход</th><th>Длина</th><th>Метод</th></tr></thead>
        <tbody>
          {segs.map((f) => {
            const p = f.properties;
            return (
              <tr key={p.object_id + p.variant}>
                <td>{p.object_id}</td>
                <td>{p.role === 'trunk' ? 'ствол' : 'ветвь'}</td>
                <td className="num">{p.diameter_mm}</td>
                <td className="num">{p.flow_tph}</td>
                <td className="num">{p.length_m}</td>
                <td>{p.method === 'special_passage' ? 'спецпроход' : 'открытый'}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}

function ReconTable({ result, variantRank }) {
  const items = result.features.filter(
    (f) => f.properties.variant === variantRank
      && (f.properties.object_type === 'reconstruction_segment'
        || f.properties.object_type === 'reconstruction_chamber'));
  if (!items.length) return null;
  return (
    <section className="dit-card">
      <h3>Реконструкция существующей сети ({items.length})</h3>
      <table>
        <thead><tr><th>ID</th><th>Тип</th><th>Ду</th><th>+Расход</th><th>Стоимость</th></tr></thead>
        <tbody>
          {items.map((f) => {
            const p = f.properties;
            return (
              <tr key={p.object_id}>
                <td>{p.object_id}</td>
                <td>{p.object_type === 'reconstruction_chamber' ? 'камера' : 'участок'}</td>
                <td className="num">{p.existing_diameter_mm
                  ? `${p.existing_diameter_mm}→${p.required_diameter_mm}` : '—'}</td>
                <td className="num">{p.added_flow_tph ?? '—'}</td>
                <td className="num">{(p.cost_rub / 1e6).toFixed(2)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}

function Warnings({ result }) {
  const warnings = result.metadata?.warnings ?? [];
  const unconnected = result.metadata?.unconnected_ids ?? [];
  if (!warnings.length && !unconnected.length) return null;
  return (
    <section className="dit-card warn">
      <h3>Предупреждения</h3>
      <ul>
        {unconnected.length > 0 && <li>Без маршрута: {unconnected.join(', ')}</li>}
        {warnings.map((w, i) => <li key={i}>{w}</li>)}
      </ul>
    </section>
  );
}
