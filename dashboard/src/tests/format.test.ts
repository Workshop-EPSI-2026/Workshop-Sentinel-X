// Libellés et niveaux affichés à l'opérateur.
import { describe, expect, it } from 'vitest';
import { factorValue } from '../components/FactorBars';
import { ALERT_TYPE, deviceLed, fmtAgo, fmtDuration, scoreLevel, severityLevel } from '../format';
import type { AlertType, Telemetry } from '../types';

describe('libellés', () => {
  it('a un libellé français pour chaque type d’incident émis par Sentinel Brain', () => {
    const emitted: AlertType[] = ['intrusion_confirmed', 'intrusion_suspected', 'loitering', 'sabotage', 'fire_risk',
      'gas_leak', 'jamming_suspected', 'cyber_attack', 'sensor_fault', 'presence_authorized', 'presence_to_verify',
      'thermal_drift', 'unusual_pattern', 'camera_degraded'];
    for (const t of emitted) expect(ALERT_TYPE[t], t).toMatch(/\S/);
  });

  it('affiche toute valeur de facteur sans planter (nombre, booléen, texte, vide)', () => {
    expect(factorValue(3)).toBe('3');
    expect(factorValue(true)).toBe('oui');
    expect(factorValue(null)).toBe('—');
    expect(factorValue('x'.repeat(100))).toHaveLength(40);
  });

  it('formate les durées', () => {
    expect(fmtAgo(100, 130)).toBe('il y a 30 s');
    expect(fmtAgo(0, 7200)).toBe('il y a 2 h');
    expect(fmtDuration(3900)).toBe('1 h 05');
  });
});

describe('niveaux', () => {
  it('classe les scores selon les seuils du dashboard', () => {
    expect([0, 39, 40, 60, 80, 100].map(scoreLevel)).toEqual(['good', 'good', 'warning', 'serious', 'critical', 'critical']);
    expect(severityLevel('critical')).toBe('critical');
  });

  it('reproduit le voyant du boîtier', () => {
    const t = { ts: 1000, mode: 'armed', edge_score: 75 } as Telemetry;
    expect(deviceLed(t, undefined, 1001).label).toBe('Alarme');
    expect(deviceLed(t, undefined, 1100).label).toBe('Hors ligne');                // plus de mesure depuis 100 s
    expect(deviceLed(t, { device_id: 'esp-01', status: 'offline', ts: 1000 }, 1001).label).toBe('Hors ligne');
  });
});
