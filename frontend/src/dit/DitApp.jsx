// Страница ДИТ (/dit): загрузка конкурсного GeoJSON → задание →
// варианты трассировки на карте + таблицы стоимости/участков.
// Работает ТОЛЬКО с Java API: POST/GET /api/jobs.
// Результат — строго по контракту §7 техприложения: четыре типа объектов
// (heat_network, heat_chamber, technical_node, variant_summary),
// variant_id у каждого объекта, сводка — variant_summary с geometry: null.
// Врезка в существующую камеру отдельным объектом не формируется (§2.4),
// реконструкция сети не выполняется (§2.4).

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
  const [selected, setSelected] = useState(null);
  const timer = useRef(null);

  const stopPolling = () => { if (timer.current) { clearInterval(timer.current); timer.current = null; } };
  useEffect(() => stopPolling, []);

  // Открытие результата по ссылке вида /dit?job=<id>
  useEffect(() => {
    const jid = new URLSearchParams(window.location.search).get('job');
    if (!jid) return;
    (async () => {
      try {
        const fresh = await apiJob(jid);
        setJob(fresh);
        if (fresh.status === 'DONE' || fresh.status === 'PARTIAL') {
          setResult(await apiResult(jid));
        }
      } catch (e) { setError(e.message); }
    })();
  }, []);

  const onFile = useCallback(async (file) => {
    if (!file) return;
    stopPolling();
    setError(null); setResult(null); setJob(null); setSelected(null);
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

  // §10: варианты — сводные записи variant_summary
  const variants = useMemo(() => {
    const vs = (result?.features ?? [])
      .filter((f) => f.properties.object_type === 'variant_summary')
      .map((f) => f.properties);
    vs.sort((a, b) => a.rank - b.rank);
    return vs;
  }, [result]);

  const active = variants.find((v) => v.variant_id === selected)
    ?? variants.find((v) => v.rank === 1)
    ?? variants[0];

  return (
    <div className="dit">
      <header className="dit-header">
        <h1>Трассировка теплосетей · ДИТ</h1>
        <p>Загрузите совмещённый GeoJSON (EPSG:4326) — сервис построит до трёх
          вариантов подключения точек ОКС и отранжирует их
          (S = 0,7·C/25 млн + 0,3·L/100, меньше — лучше).</p>
      </header>

      <UploadZone onFile={onFile} busy={!!job && !result && !error} />

      {job && <JobCard job={job} />}
      {error && <div className="dit-error">Ошибка: {error}</div>}

      {result && active && (
        <>
          <VariantTabs variants={variants} selected={active.variant_id} onSelect={setSelected} />
          <div className="dit-main">
            <ResultMap result={result} variantId={active.variant_id} />
            <div className="dit-side">
              <CostTable variant={active} />
              <SegmentsTable result={result} variantId={active.variant_id} />
              <Unconnected variant={active} />
              <a className="dit-download" href={`/api/jobs/${job.id}/result`} download>
                ⬇ Скачать выходной GeoJSON (§7)
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
        <button key={v.variant_id}
          className={`dit-tab ${v.variant_id === selected ? 'active' : ''}`}
          onClick={() => onSelect(v.variant_id)}>
          <b>Вариант #{v.rank}</b>
          <small>{(v.calculated_cost / 1e6).toFixed(1)} млн ₽ · {Math.round(v.new_network_length)} м · S={v.score}
            {v.rank === 1 ? ' · ★ рекомендуемый' : ''}</small>
        </button>
      ))}
    </div>
  );
}

// ---------- Карта (SVG, проекция lon/lat → экран) ----------

const COLORS = {
  base: '#0984e3',
  special: '#a55eea',
  heat_chamber: '#00b894',
  technical_node: '#b2bec3',
};

function ResultMap({ result, variantId }) {
  const feats = useMemo(
    () => result.features.filter(
      (f) => f.geometry && f.properties.variant_id === variantId),
    [result, variantId]);

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
  const ofType = (t) => feats.filter((f) => f.properties.object_type === t);

  return (
    <svg className="dit-map" viewBox="0 0 880 560">
      {/* новые участки: base — сплошная, special — пунктир */}
      {ofType('heat_network').map((f) => {
        const p = f.properties;
        const special = p.laying_method === 'special';
        return (
          <path key={p.id} d={path(f.geometry.coordinates)}
            stroke={special ? COLORS.special : COLORS.base}
            strokeWidth={1.5 + p.diameter / 120} fill="none"
            strokeDasharray={special ? '6 4' : undefined} strokeLinecap="round">
            <title>{p.id} · Ду{p.diameter} · {p.flow_tph} т/ч · {p.length} м
              {special ? ' · спецпроход' : ''}</title>
          </path>
        );
      })}
      {/* точечные объекты */}
      {ofType('heat_chamber').map((f) => {
        const [sx, sy] = dot(f.geometry.coordinates);
        return <circle key={f.properties.id} cx={sx} cy={sy} r="7"
          fill={COLORS.heat_chamber} stroke="#013" strokeWidth="1.5">
          <title>Новая камера {f.properties.id} · Ду{f.properties.diameter}</title></circle>;
      })}
      {ofType('technical_node').map((f) => {
        const [sx, sy] = dot(f.geometry.coordinates);
        return <rect key={f.properties.id} x={sx - 5} y={sy - 5} width="10" height="10"
          fill="none" stroke={COLORS.technical_node} strokeWidth="2">
          <title>Технический узел {f.properties.id}</title></rect>;
      })}
      <Legend />
    </svg>
  );
}

function Legend() {
  const items = [
    ['новый участок (base)', COLORS.base],
    ['спецпроход (special)', COLORS.special],
    ['новая камера', COLORS.heat_chamber],
    ['технический узел', COLORS.technical_node],
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

// ---------- Таблицы (статьи §10.7) ----------

function CostTable({ variant }) {
  const segments = variant.segments_cost
    ?? (variant.construction_cost - (variant.chamber_construction_cost ?? 0)
        - (variant.existing_chamber_tie_in_cost ?? 0));
  const tieIns = variant.existing_chamber_tie_in_count ?? 0;
  const rows = [
    ['Новые участки', segments],
    ['Новые камеры', variant.chamber_construction_cost],
    [`Врезки в существующие камеры (${tieIns} шт × 5 млн)`, variant.existing_chamber_tie_in_cost],
    ['Штраф за неподключённые точки', variant.unconnected_penalty],
  ];
  return (
    <section className="dit-card">
      <h3>Калькуляция · S = {variant.score} · место #{variant.rank}</h3>
      <table>
        <tbody>
          {rows.map(([name, val]) => (
            <tr key={name}><td>{name}</td><td className="num">{((val ?? 0) / 1e6).toFixed(2)}</td></tr>
          ))}
          <tr className="total"><td>ИТОГО (расчётная стоимость)</td>
            <td className="num">{(variant.calculated_cost / 1e6).toFixed(2)}</td></tr>
        </tbody>
      </table>
      <p className="dit-note">млн ₽ · строительство {(variant.construction_cost / 1e6).toFixed(2)} млн ₽ ·
        новая сеть {Math.round(variant.new_network_length)} м ·
        S = 0,7·C/25 млн + 0,3·L/100</p>
    </section>
  );
}

function SegmentsTable({ result, variantId }) {
  const segs = result.features.filter(
    (f) => f.properties.variant_id === variantId
      && f.properties.object_type === 'heat_network');
  if (!segs.length) return null;
  return (
    <section className="dit-card">
      <h3>Новые участки ({segs.length})</h3>
      <table>
        <thead><tr><th>ID</th><th>Узлы</th><th>Ду, мм</th><th>Расход</th><th>Длина</th><th>Глубина</th><th>Метод</th></tr></thead>
        <tbody>
          {segs.map((f) => {
            const p = f.properties;
            return (
              <tr key={p.id}>
                <td>{p.id}</td>
                <td>{p.start_node_id} → {p.end_node_id}</td>
                <td className="num">{p.diameter}</td>
                <td className="num">{p.flow_tph}</td>
                <td className="num">{p.length}</td>
                <td className="num">{p.depth_start != null ? `${p.depth_start}→${p.depth_end}` : '—'}</td>
                <td>{p.laying_method === 'special' ? 'спецпроход' : 'обычная'}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}

function Unconnected({ variant }) {
  const ids = variant.unconnected_oks_ids ?? [];
  if (!ids.length) return null;
  return (
    <section className="dit-card warn">
      <h3>Неподключённые ОКС</h3>
      <ul>
        <li>Без маршрута: {ids.join(', ')} — штраф 100 млн ₽ + 0,5 млн ₽ × расход
          каждой точки учтён в калькуляции
          ({(variant.unconnected_penalty / 1e6).toFixed(1)} млн ₽)</li>
      </ul>
    </section>
  );
}
