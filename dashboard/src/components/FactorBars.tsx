import { FACTOR, fmtNum } from '../format';
import type { Factor } from '../types';

// Facteurs qui expliquent un incident : une seule série (couleur 1), valeur au bout de la barre
export function FactorBars({ factors }: { factors: Factor[] }) {
  if (!factors.length) return null;
  const sorted = [...factors].sort((a, b) => b.contribution - a.contribution);
  return (
    <ul className="factors" aria-label="Facteurs qui ont le plus pesé">
      {sorted.map((f) => (
        <li key={f.name} className="factor">
          <span className="factor-name">
            {FACTOR[f.name] ?? f.name} <span className="muted">({fmtNum(f.value, Number.isInteger(f.value) ? 0 : 2)})</span>
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
