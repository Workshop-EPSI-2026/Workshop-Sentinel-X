import { useId, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react';
import { fmtNum, fmtTime } from '../format';
import { useWidth } from './useWidth';

export interface Pt {
  t: number;
  v: number;
}

export interface Threshold {
  value: number;
  level: 'warning' | 'critical';
  label: string;
}

interface Props {
  title: string;
  unit: string;
  points: Pt[];
  now: number;
  windowS: number;
  digits?: number;
  thresholds?: Threshold[];
  fixedDomain?: [number, number];
  minSpan?: number;
  gapS?: number; // au-delà, la courbe s'interrompt (boîtier hors ligne)
  height?: number;
}

const DEFAULT_H = 156;
const PAD = { l: 44, r: 70, t: 12, b: 26 };

function niceStep(span: number, count: number) {
  const raw = span / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const n = raw / mag;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10) * mag;
}

function domainOf(values: number[], fixed: [number, number] | undefined, minSpan: number) {
  let min: number;
  let max: number;
  if (fixed) [min, max] = fixed;
  else if (!values.length) [min, max] = [0, 1];
  else {
    min = Math.min(...values);
    max = Math.max(...values);
    if (max - min < minSpan) {
      const c = (max + min) / 2;
      min = c - minSpan / 2;
      max = c + minSpan / 2;
    }
  }
  const step = niceStep(max - min, 4);
  const lo = fixed ? min : Math.floor(min / step) * step;
  let hi = fixed ? max : Math.ceil(max / step) * step;
  if (hi <= lo) hi = lo + step;
  const ticks: number[] = [];
  for (let v = lo; v <= hi + step / 2; v += step) ticks.push(Math.round(v * 1e6) / 1e6);
  return { lo, hi, ticks };
}

export function LineChart({ title, unit, points, now, windowS, digits = 0, thresholds = [], fixedDomain, minSpan = 1, gapS = 10, height }: Props) {
  const H = height ?? DEFAULT_H;
  const wrap = useRef<HTMLDivElement>(null);
  const width = useWidth(wrap);
  const [hover, setHover] = useState<number | null>(null);
  const [table, setTable] = useState(false);
  const titleId = useId();

  const x0 = now - windowS;
  const pts = useMemo(() => points.filter((p) => p.t >= x0), [points, x0]);
  const { lo, hi, ticks } = useMemo(() => domainOf(pts.map((p) => p.v), fixedDomain, minSpan), [pts, fixedDomain, minSpan]);

  const iw = Math.max(10, width - PAD.l - PAD.r);
  const ih = H - PAD.t - PAD.b;
  const X = (t: number) => PAD.l + ((t - x0) / windowS) * iw;
  const Y = (v: number) => PAD.t + ((hi - v) / (hi - lo)) * ih;
  const base = Y(lo);

  // Segments continus : une coupure du boîtier laisse un trou plutôt qu'une ligne trompeuse
  const segments: Pt[][] = [];
  for (const p of pts) {
    const seg = segments[segments.length - 1];
    if (!seg || p.t - seg[seg.length - 1].t > gapS) segments.push([p]);
    else seg.push(p);
  }
  const line = segments.map((s) => s.map((p, i) => `${i ? 'L' : 'M'}${X(p.t).toFixed(1)},${Y(p.v).toFixed(1)}`).join('')).join('');
  const area = segments
    .map((s) => `M${X(s[0].t).toFixed(1)},${base}` + s.map((p) => `L${X(p.t).toFixed(1)},${Y(p.v).toFixed(1)}`).join('') + `L${X(s[s.length - 1].t).toFixed(1)},${base}Z`)
    .join('');

  const xTicks: number[] = [];
  for (let t = Math.ceil(x0 / 300) * 300; t <= now; t += 300) xTicks.push(t);

  const visible = thresholds.filter((th) => th.value >= lo && th.value <= hi);
  const hidden = thresholds.filter((th) => th.value < lo || th.value > hi);
  const last = pts[pts.length - 1];
  const fmt = (v: number) => `${fmtNum(v, digits)}${unit ? ` ${unit}` : ''}`;

  function nearest(clientX: number, rect: DOMRect) {
    const t = x0 + ((clientX - rect.left - PAD.l) / iw) * windowS;
    let best = 0;
    for (let i = 1; i < pts.length; i++) if (Math.abs(pts[i].t - t) < Math.abs(pts[best].t - t)) best = i;
    return best;
  }

  function onMove(e: PointerEvent<SVGSVGElement>) {
    if (pts.length) setHover(nearest(e.clientX, e.currentTarget.getBoundingClientRect()));
  }

  function onKey(e: KeyboardEvent<SVGSVGElement>) {
    if (!pts.length) return;
    const cur = hover ?? pts.length - 1;
    if (e.key === 'ArrowLeft') setHover(Math.max(0, cur - 1));
    else if (e.key === 'ArrowRight') setHover(Math.min(pts.length - 1, cur + 1));
    else if (e.key === 'Home') setHover(0);
    else if (e.key === 'End') setHover(pts.length - 1);
    else if (e.key === 'Escape') setHover(null);
    else return;
    e.preventDefault();
  }

  const h = hover !== null ? pts[Math.min(hover, pts.length - 1)] : undefined;
  const tipLeft = h ? Math.min(Math.max(X(h.t), 70), width - 70) : 0;

  return (
    <figure className="card chart">
      <figcaption className="chart-head">
        <h3 id={titleId}>{title}</h3>
        <button type="button" className="link-btn" onClick={() => setTable((v) => !v)} aria-pressed={table}>
          {table ? 'Graphique' : 'Tableau'}
        </button>
      </figcaption>

      {table && (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr><th>Heure</th><th className="num">{title}</th></tr>
            </thead>
            <tbody>
              {[...pts].reverse().slice(0, 60).map((p) => (
                <tr key={p.t}><td>{fmtTime(p.t)}</td><td className="num">{fmt(p.v)}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div ref={wrap} className="chart-plot" style={{ height: H, display: table ? 'none' : undefined }}>
          {width > 0 && (
            <svg
              width={width}
              height={H}
              role="img"
              aria-labelledby={titleId}
              aria-describedby={`${titleId}-desc`}
              tabIndex={0}
              onPointerMove={onMove}
              onPointerLeave={() => setHover(null)}
              onFocus={() => setHover(pts.length ? pts.length - 1 : null)}
              onBlur={() => setHover(null)}
              onKeyDown={onKey}
            >
              <desc id={`${titleId}-desc`}>
                {last ? `Dernière valeur ${fmt(last.v)} à ${fmtTime(last.t)}. Flèches gauche et droite pour parcourir.` : 'Aucune donnée.'}
              </desc>
              {ticks.map((v) => (
                <g key={v}>
                  <line x1={PAD.l} x2={PAD.l + iw} y1={Y(v)} y2={Y(v)} className={v === lo ? 'axis' : 'grid'} />
                  <text x={PAD.l - 8} y={Y(v)} className="tick" textAnchor="end" dominantBaseline="middle">{fmtNum(v, digits)}</text>
                </g>
              ))}
              {xTicks.map((t) => (
                <text key={t} x={X(t)} y={H - 6} className="tick" textAnchor="middle">{fmtTime(t, false)}</text>
              ))}

              {visible.map((th) => (
                <g key={th.label}>
                  <line x1={PAD.l} x2={PAD.l + iw} y1={Y(th.value)} y2={Y(th.value)} className="threshold" style={{ stroke: `var(--status-${th.level === 'critical' ? 'critical' : 'warning'})` }} />
                  <text x={PAD.l + 6} y={Y(th.value) - 4} className="threshold-label">{th.label} {fmtNum(th.value, digits)}</text>
                </g>
              ))}

              <path d={area} className="series-area" />
              <path d={line} className="series-line" />

              {last && (
                <g>
                  <circle cx={X(last.t)} cy={Y(last.v)} r={4} className="series-dot" />
                  <text x={X(last.t) + 10} y={Y(last.v)} className="end-label" dominantBaseline="middle">{fmt(last.v)}</text>
                </g>
              )}

              {h && (
                <g pointerEvents="none">
                  <line x1={X(h.t)} x2={X(h.t)} y1={PAD.t} y2={base} className="crosshair" />
                  <circle cx={X(h.t)} cy={Y(h.v)} r={4} className="series-dot" />
                </g>
              )}
            </svg>
          )}
          {h && (
            <div className="tooltip" style={{ left: tipLeft }} role="status">
              <span className="tooltip-key" />
              <strong>{fmt(h.v)}</strong>
              <span className="muted">{fmtTime(h.t)}</span>
            </div>
          )}
          {!pts.length && <p className="chart-empty muted">En attente de mesures…</p>}
      </div>

      {hidden.length > 0 && !table && (
        <p className="chart-note muted">
          Hors échelle : {hidden.map((th) => `${th.label.toLowerCase()} ${fmt(th.value)}`).join(' · ')}
        </p>
      )}
    </figure>
  );
}
