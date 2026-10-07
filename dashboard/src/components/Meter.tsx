import type { CSSProperties } from 'react';
import { scoreLevel } from '../format';
import { LevelTag } from './StatusIcon';

// Score de domaine (0-100) : le remplissage porte la gravité, la piste est un ton plus clair de la même couleur
export function Meter({ label, value }: { label: string; value: number }) {
  const level = scoreLevel(value);
  const v = Math.round(Math.min(100, Math.max(0, value)));
  return (
    <div className="meter">
      <div className="meter-head">
        <span className="meter-label">{label}</span>
        <span className="meter-value">{v}</span>
      </div>
      <div
        className="meter-track"
        style={{ '--c': `var(--status-${level})` } as CSSProperties}
        role="meter"
        aria-label={`Score ${label}`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={v}
      >
        <div className="meter-fill" style={{ width: `${v}%` }} />
      </div>
      <LevelTag level={level} />
    </div>
  );
}
