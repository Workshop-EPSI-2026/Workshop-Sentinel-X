import { useEffect, useState } from 'react';
import { LevelTag } from '../components/StatusIcon';
import { fmtAgo, fmtDuration, fmtNum } from '../format';
import { useApp, useDevices, useNow } from '../state';
import type { DeviceHealth, SystemHealth } from '../types';

function rssiLevel(rssi: number) {
  if (rssi >= -67) return { level: 'good' as const, label: 'Bon' };
  if (rssi >= -78) return { level: 'warning' as const, label: 'Faible' };
  return { level: 'critical' as const, label: 'Très faible' };
}

export function Systeme() {
  const { state, source } = useApp();
  const now = useNow(5000);
  const devices = useDevices();
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const load = () =>
      source.getHealth()
        .then((h) => alive && (setHealth(h), setError(null)))
        .catch((e) => alive && setError(e instanceof Error ? e.message : String(e)));
    load();
    const t = window.setInterval(load, 5000);
    return () => {
      alive = false;
      window.clearInterval(t);
    };
  }, [source]);

  // La santé poussée en temps réel (WebSocket) prime sur celle du dernier appel /health
  const deviceHealth = (id: string): DeviceHealth | undefined => state.health[id] ?? health?.devices.find((d) => d.device_id === id);

  return (
    <div className={`view ${error ? 'stale' : ''}`}>
      {error && <p className="card error" role="alert">Santé du serveur indisponible : {error}</p>}

      <section className="sys-row">
        <div className="card">
          <h2 className="card-title">Services</h2>
          <ul className="services">
            <li>
              <LevelTag level={state.link === 'online' ? 'good' : 'critical'} label="Temps réel (WebSocket)" />
              <span className="muted small">{state.link === 'online' ? 'connecté' : state.link === 'connecting' ? 'connexion…' : 'déconnecté'}</span>
            </li>
            {health?.services.map((s) => (
              <li key={s.name}>
                <LevelTag level={s.ok ? 'good' : 'critical'} label={s.name} />
                <span className="muted small">{s.detail ?? (s.ok ? 'opérationnel' : 'en panne')}</span>
              </li>
            ))}
          </ul>
        </div>
        <div className="card">
          <h2 className="card-title">PC serveur</h2>
          <div className="tiles">
            <div className="tile"><span className="tile-label">Processeur</span><span className="tile-value">{health ? `${fmtNum(health.server.cpu_pct)} %` : '—'}</span></div>
            <div className="tile"><span className="tile-label">Mémoire</span><span className="tile-value">{health ? `${fmtNum(health.server.mem_pct)} %` : '—'}</span></div>
            <div className="tile"><span className="tile-label">En service depuis</span><span className="tile-value">{health ? fmtDuration(health.server.uptime_s) : '—'}</span></div>
          </div>
        </div>
      </section>

      <section className="card">
        <h2 className="card-title">Boîtiers</h2>
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th>Boîtier</th><th>État</th><th className="num">Signal Wi-Fi</th><th className="num">Tampon</th>
                <th className="num">Mémoire libre</th><th className="num">Puce</th><th className="num">Déconnexions</th>
                <th className="num">Erreurs TLS</th><th>Firmware</th><th>En service</th><th>Santé reçue</th>
              </tr>
            </thead>
            <tbody>
              {devices.map((d) => {
                const h = deviceHealth(d.id);
                const st = state.status[d.id];
                const r = h ? rssiLevel(h.rssi) : null;
                return (
                  <tr key={d.id}>
                    <td><strong>{d.id}</strong><br /><span className="muted small">{d.label}</span></td>
                    <td><LevelTag level={st?.status === 'offline' ? 'critical' : 'good'} label={st?.status === 'offline' ? 'Hors ligne' : 'En ligne'} /></td>
                    <td className="num">{h && r ? <>{h.rssi} dBm <LevelTag level={r.level} label={r.label} /></> : '—'}</td>
                    <td className="num">{h ? fmtNum(h.buffer_len) : '—'}</td>
                    <td className="num">{h ? `${fmtNum(h.heap_free / 1024)} Ko` : '—'}</td>
                    <td className="num">{h ? `${fmtNum(h.chip_temp_c)} °C` : '—'}</td>
                    <td className="num">{h ? `${h.wifi_disconnects} Wi-Fi · ${h.mqtt_reconnects} MQTT` : '—'}</td>
                    <td className="num">{h ? fmtNum(h.tls_errors) : '—'}</td>
                    <td>{h?.fw_version ?? '—'}</td>
                    <td>{h ? fmtDuration(h.uptime_s) : '—'}</td>
                    <td>{h ? fmtAgo(h.ts, now) : '—'}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
