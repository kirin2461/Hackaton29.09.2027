// Продольный профиль (разрез) трассы — SVG-график.
// Верхняя линия — рельеф, нижняя — труба на глубине заложения,
// жёлтые вертикали — переходы под дорогами.

export default function RouteProfile({ profile }) {
  if (!profile?.samples?.length) return null;
  const W = 300;
  const H = 120;
  const PAD = { l: 34, r: 6, t: 8, b: 18 };
  const iw = W - PAD.l - PAD.r;
  const ih = H - PAD.t - PAD.b;

  const samples = profile.samples;
  const dMax = samples[samples.length - 1].d || 1;
  const zs = samples.flatMap((s) => [s.ground, s.pipe]);
  const zMin = Math.min(...zs);
  const zMax = Math.max(...zs);
  const zSpan = zMax - zMin || 1;

  const X = (d) => PAD.l + (d / dMax) * iw;
  const Y = (z) => PAD.t + (1 - (z - zMin) / zSpan) * ih;
  const line = (key) => samples
    .map((s, i) => `${i ? 'L' : 'M'}${X(s.d).toFixed(1)},${Y(s[key]).toFixed(1)}`)
    .join(' ');

  // Подписи отметок: мин/макс земли.
  const gMin = Math.min(...samples.map((s) => s.ground));
  const gMax = Math.max(...samples.map((s) => s.ground));

  return (
    <div className="profile">
      <svg viewBox={`0 0 ${W} ${H}`} width="100%">
        {/* заливка «грунт» под линией рельефа */}
        <path
          d={`${line('ground')} L${X(dMax).toFixed(1)},${Y(zMin).toFixed(1)} L${X(0).toFixed(1)},${Y(zMin).toFixed(1)} Z`}
          fill="#7a9e5f"
          opacity="0.25"
        />
        <path d={line('ground')} fill="none" stroke="#9CCC65" strokeWidth="1.8" />
        <path d={line('pipe')} fill="none" stroke="#E8590C" strokeWidth="2" />
        {profile.road_crossings.map((c) => (
          <line
            key={c.from_m}
            x1={X(c.from_m)} x2={X(c.from_m)}
            y1={PAD.t} y2={H - PAD.b}
            stroke="#F5B700" strokeWidth="2.5" opacity="0.85"
          />
        ))}
        <text x={2} y={Y(gMax) + 3} className="axis-label">{gMax.toFixed(1)}</text>
        <text x={2} y={Y(gMin) + 3} className="axis-label">{gMin.toFixed(1)}</text>
        <text x={PAD.l} y={H - 5} className="axis-label">0</text>
        <text x={W - PAD.r} y={H - 5} className="axis-label" textAnchor="end">
          {profile.length_m} м
        </text>
      </svg>
      <p className="hint">
        Разрез: рельеф (зелёная) vs труба на −{profile.depth_m} м (оранжевая).
        Жёлтое — переходы под дорогами ({profile.road_crossings.length}).
        Макс. уклон {profile.max_slope_pct}%, перепад {profile.elevation_gain_m} м.
      </p>
    </div>
  );
}
