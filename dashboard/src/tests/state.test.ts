// État du dashboard : ce que l'écran affiche à partir des messages temps réel de l'API.
import { describe, expect, it } from 'vitest';
import { initial, reducer, WINDOW_S, type Action } from '../state';
import type { Alert, Scores, Telemetry } from '../types';

const tel = (seq: number, ts: number, extra: Partial<Telemetry> = {}): Telemetry => ({
  device_id: 'esp-01', seq, boot_id: 'b1', ts, temp_c: 22, hum_pct: 45, gas_mv: 400, gas_ratio: 1,
  gas_do: false, pir: false, pir_count: 0, mode: 'armed', edge_score: 0, replay: false, ...extra,
});

const alert = (id: number, extra: Partial<Alert> = {}): Alert => ({
  id, status: 'open', count: 1, device_id: 'cam-01', source: 'brain', domain: 'physical', type: 'intrusion_confirmed',
  severity: 'critical', score: 95, eta_min: null, ts: 1000, explanation: 'Intrus', factors: [], details: {}, ...extra,
});

const run = (...actions: Action[]) => actions.reduce(reducer, initial);

describe('télémétrie', () => {
  it('garde les mesures triées et sans doublon, même rejouées depuis le tampon du boîtier', () => {
    const s = run(
      { type: 'telemetry', data: tel(1, 100) },
      { type: 'telemetry', data: tel(3, 104) },
      { type: 'telemetry', data: tel(2, 102, { replay: true }) },   // arrivée en retard
      { type: 'telemetry', data: tel(3, 104) },                     // doublon
    );
    expect(s.telemetry['esp-01'].map((t) => t.seq)).toEqual([1, 2, 3]);
  });

  it('oublie ce qui sort de la fenêtre affichée', () => {
    const s = run({ type: 'telemetry', data: tel(1, 0) }, { type: 'telemetry', data: tel(2, WINDOW_S + 10) });
    expect(s.telemetry['esp-01'].map((t) => t.seq)).toEqual([2]);
  });

  it("fusionne l'historique chargé avec le direct", () => {
    const s = run({ type: 'telemetry', data: tel(5, 110) }, { type: 'history', deviceId: 'esp-01', items: [tel(4, 108), tel(5, 110)] });
    expect(s.telemetry['esp-01'].map((t) => t.seq)).toEqual([4, 5]);
  });
});

describe('incidents', () => {
  it('ajoute un nouvel incident en tête et met à jour un incident regroupé', () => {
    const s = run(
      { type: 'alerts', alerts: [alert(1, { type: 'gas_leak' })] },
      { type: 'alert', data: alert(2) },
      { type: 'alert', data: alert(1, { type: 'gas_leak', count: 4, status: 'acknowledged' }) },
    );
    expect(s.alerts.map((a) => a.id)).toEqual([2, 1]);
    expect(s.alerts[1]).toMatchObject({ count: 4, status: 'acknowledged' });
  });
});

describe('scores', () => {
  const sc = (ts: number, global: number): Scores => ({ ts, global, environment: 0, physical: global, cyber: 0 });

  it('ordonne les scores et ignore un doublon', () => {
    const s = run({ type: 'score', data: sc(10, 20) }, { type: 'score', data: sc(5, 10) }, { type: 'score', data: sc(10, 99) });
    expect(s.scores.map((x) => [x.ts, x.global])).toEqual([[5, 10], [10, 20]]);
  });
});

describe('robustesse', () => {
  it("ignore un type de message inconnu (API plus récente) au lieu d'afficher un écran blanc", () => {
    const s = reducer(initial, { type: 'nouveau_type', data: {} } as unknown as Action);
    expect(s).toBe(initial);
  });

  it("garde l'état en direct de la caméra", () => {
    const s = run({ type: 'vision', data: { device_id: 'cam-01', ts: 1, fps: 10, masked: true, low_light: false, frozen: false, zone_count: 0, persons: [] } });
    expect(s.vision['cam-01'].masked).toBe(true);
  });
});
