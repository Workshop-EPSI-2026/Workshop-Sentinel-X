import { FACTOR, fmtNum } from '../format';
import type { Factor } from '../types';

function factorValue(v: Factor['value']): string {
  if (typeof v === 'number') return fmtNum(v, Number.isInteger(v) ? 0 : 2);
  if (typeof v === 'boolean') return v ? 'oui' : 'non';
  return v == null ? '—' : String(v).slice(0, 40);
}

// Facteurs qui expliquent un incident : une seule série (couleur 1), valeur au bout de la barre
export function FactorBars({ factors }: { factors: Factor[] }) {
  if (!factors.length) return null;
  const sorted = [...factors].sort((a, b) => b.contribution - a.contribution);
  return (
    <ul className="factors" aria-label="Facteurs qui ont le plus pesé">
      {sorted.map((f) => (
        <li key={f.name} className="factor">
          <span className="factor-name">
            {FACTOR[f.name] ?? f.name} <span className="muted">({factorValue(f.value)})</span>
          </span>
          <span className="factor-bar">
            <span className="factor-fill" style={{ width: `${Math.max(2, f.contribution * 100)}%` }} />
            <span className="factor-value">{Math.round(f.contribution * 100)} %</span>
          </span>
        </li>
      ))}
    </ul>
  );
}
