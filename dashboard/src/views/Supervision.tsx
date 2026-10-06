import { useState } from 'react';
import { LineChart, type Threshold } from '../components/LineChart';
import { Meter } from '../components/Meter';
import { LevelTag, StatusIcon } from '../components/StatusIcon';
import { ALERT_TYPE, MODE, SCORE_STEPS, deviceLed, fmtAgo, fmtNum, scoreLevel, severityLevel } from '../format';
import { WINDOW_S, useApp, useDevices, useNow } from '../state';
import type { Command, SiteProfile, ThresholdKey } from '../types';

function thresholdsFor(profile: SiteProfile | undefined, key: ThresholdKey): Threshold[] {
  const th = profile?.thresholds[key];
  if (!th) return [];
  return [
    { value: th.warning, level: 'warning', label: 'Avertissement' },
    { value: th.critical, level: 'critical', label: 'Critique' },
  ];
}

const SCORE_THRESHOLDS: Threshold[] = [
  { value: SCORE_STEPS.warning, level: 'warning', label: 'Vigilance' },
  { value: SCORE_STEPS.critical, level: 'critical', label: 'Critique' },
];

export function Supervision() {
  const { state } = useApp();
  const now = useNow();
  const devices = useDevices();
  const score = state.scores[state.scores.length - 1];
  const open = state.alerts.filter((a) => a.status === 'open').sort((a, b) => b.score - a.score);

  return (
    <div className="view">
      <section className="score-row">
        <div className="card hero">
          <h2 className="card-title">Sentinel Score</h2>
          {score ? (
            <>
              <p className="hero-value">{Math.round(score.global)}</p>
              <LevelTag level={scoreLevel(score.global)} />
              <p className="muted small">Mis à jour {fmtAgo(score.ts, now)}</p>
            </>
          ) : (
            <p className="muted">En attente de Sentinel Brain…</p>
          )}
        </div>
        <div className="card meters">
          <h2 className="card-title">Scores par domaine</h2>
          <Meter label="Environnement" value={score?.environment ?? 0} />
          <Meter label="Physique" value={score?.physical ?? 0} />
          <Meter label="Cyber" value={score?.cyber ?? 0} />
        </div>
        <LineChart
          title="Sentinel Score (15 min)"
          unit=""
          points={state.scores.map((s) => ({ t: s.ts, v: s.global }))}
          now={now}
          windowS={WINDOW_S}
          fixedDomain={[0, 100]}
          thresholds={SCORE_THRESHOLDS}
          height={250}
        />
      </section>

      {open.length > 0 && (
        <section className="card">
          <div className="card-head">
            <h2 className="card-title">Incidents ouverts ({open.length})</h2>
            <a href="#/incidents" className="link-btn">Tout voir</a>
          </div>
          <ul className="incident-mini">
            {open.slice(0, 4).map((a) => (
              <li key={a.id}>
                <StatusIcon level={severityLevel(a.severity)} />
                <strong>{ALERT_TYPE[a.type]}</strong>
                <span className="muted">{a.explanation}</span>
                <span className="muted nowrap">{fmtAgo(a.ts, now)}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {devices.map((d) => (
        <DevicePanel key={d.id} id={d.id} label={d.label} now={now} />
      ))}
    </div>
  );
}

function DevicePanel({ id, label, now }: { id: string; label: string; now: number }) {
  const { state, source } = useApp();
  const list = state.telemetry[id] ?? [];
  const t = list[list.length - 1];
  const led = deviceLed(t, state.status[id], now);
  const profile = state.config?.profile;
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function send(command: Command, text: string, confirmText?: string) {
    if (confirmText && !window.confirm(confirmText)) return;
    setBusy(true);
    setMessage(null);
    try {
      await source.sendCommand(id, command);
      setMessage(`${text} : commande envoyée.`);
    } catch (e) {
      setMessage(`${text} : échec (${e instanceof Error ? e.message : e}).`);
    } finally {
      setBusy(false);
    }
  }

  const tiles = t
    ? [
        { label: 'Température', value: `${fmtNum(t.temp_c)} °C` },
        { label: 'Humidité', value: `${fmtNum(t.hum_pct)} %` },
        { label: 'Gaz (ratio)', value: fmtNum(t.gas_ratio, 2), note: t.gas_do ? 'Seuil matériel dépassé' : undefined },
        { label: 'Mouvements / min', value: fmtNum(t.pir_count), note: t.pir ? 'Mouvement en cours' : undefined },
        { label: 'Garde locale', value: fmtNum(t.edge_score), level: scoreLevel(t.edge_score) },
      ]
    : [];

  return (
    <section className="card device">
      <div className="device-head">
        <div>
          <h2 className="card-title">{label}</h2>
          <p className="muted small">
            {id}
            {t && ` · ${MODE[t.mode]} · dernière mesure ${fmtAgo(t.ts, now)}${t.replay ? ' (rejouée)' : ''}`}
          </p>
        </div>
        <span className="led-badge">
          <span className="led" style={{ background: led.color }} aria-hidden="true" />
          {led.label}
        </span>
      </div>

      {t ? (
        <div className="tiles">
          {tiles.map((tile) => (
            <div key={tile.label} className="tile">
              <span className="tile-label">{tile.label}</span>
              <span className="tile-value">{tile.value}</span>
              {tile.level && <LevelTag level={tile.level} />}
              {tile.note && <span className="tile-note">{tile.note}</span>}
            </div>
          ))}
        </div>
      ) : (
        <p className="muted">Aucune mesure reçue de ce boîtier.</p>
      )}

      <div className="charts">
        <LineChart title="Température" unit="°C" points={list.map((m) => ({ t: m.ts, v: m.temp_c }))} now={now} windowS={WINDOW_S} minSpan={4} thresholds={thresholdsFor(profile, 'temp_c')} />
        <LineChart title="Humidité" unit="%" points={list.map((m) => ({ t: m.ts, v: m.hum_pct }))} now={now} windowS={WINDOW_S} minSpan={10} thresholds={thresholdsFor(profile, 'hum_pct')} />
        <LineChart title="Gaz (ratio / ligne de base)" unit="" digits={2} points={list.map((m) => ({ t: m.ts, v: m.gas_ratio }))} now={now} windowS={WINDOW_S} minSpan={0.2} thresholds={thresholdsFor(profile, 'gas_ratio')} />
      </div>

      <div className="commands" aria-label="Commandes du boîtier">
        <button type="button" className="btn danger" disabled={busy} onClick={() => send({ cmd: 'alarm', on: true }, 'Alarme', 'Déclencher l\'alarme sonore du boîtier ?')}>Déclencher l'alarme</button>
        <button type="button" className="btn" disabled={busy} onClick={() => send({ cmd: 'alarm', on: false }, 'Arrêt de l\'alarme')}>Couper l'alarme</button>
        {t?.mode === 'maintenance' ? (
          <button type="button" className="btn" disabled={busy} onClick={() => send({ cmd: 'mode', value: 'armed' }, 'Mode surveillance')}>Passer en surveillance</button>
        ) : (
          <button type="button" className="btn" disabled={busy} onClick={() => send({ cmd: 'mode', value: 'maintenance' }, 'Mode maintenance', 'Passer en maintenance coupe les alarmes du boîtier. Continuer ?')}>Passer en maintenance</button>
        )}
        <button type="button" className="btn" disabled={busy} onClick={() => send({ cmd: 'recalibrate' }, 'Recalibrage')}>Recalibrer</button>
        <button type="button" className="btn" disabled={busy} onClick={() => send({ cmd: 'reboot' }, 'Redémarrage', `Redémarrer ${id} ?`)}>Redémarrer</button>
        {message && <span className="muted small" role="status">{message}</span>}
      </div>
    </section>
  );
}
