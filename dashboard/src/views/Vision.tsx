import { useEffect, useState } from 'react';
import { LevelTag } from '../components/StatusIcon';
import { ALERT_TYPE, fmtAgo, fmtNum, severityLevel } from '../format';
import { useApp, useNow } from '../state';
import type { SystemHealth } from '../types';

export function Vision() {
  const { state, source } = useApp();
  const now = useNow(5000);
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [videoError, setVideoError] = useState(false);
  const url = source.videoUrl();
  const vision = state.config?.profile.vision;
  const alerts = state.alerts.filter((a) => a.source === 'vision' || a.type.startsWith('intrusion') || a.type === 'loitering').slice(0, 6);

  useEffect(() => {
    let alive = true;
    const load = () => source.getHealth().then((h) => alive && setHealth(h)).catch(() => {});
    load();
    const t = window.setInterval(load, 5000);
    return () => {
      alive = false;
      window.clearInterval(t);
    };
  }, [source]);

  return (
    <div className="view vision-layout">
      <section className="card video-card">
        <h2 className="card-title">Flux annoté de la caméra</h2>
        <div className="video-frame">
          {url && !videoError ? (
            <img src={url} alt="Flux vidéo annoté : personnes détectées et zone interdite" onError={() => setVideoError(true)} />
          ) : (
            <div className="video-placeholder">
              <p>{url ? 'Flux indisponible : vérifier que la vision tourne sur le PC serveur (ai\\vision\\run-windows.ps1).' : 'Pas de flux vidéo en mode démo.'}</p>
              {url && <button type="button" className="btn" onClick={() => setVideoError(false)}>Réessayer</button>}
            </div>
          )}
        </div>
      </section>

      <aside className="vision-side">
        <section className="card">
          <h2 className="card-title">Performances</h2>
          <div className="tiles two">
            <div className="tile"><span className="tile-label">Images / s</span><span className="tile-value">{health?.vision ? fmtNum(health.vision.fps, 1) : '—'}</span></div>
            <div className="tile"><span className="tile-label">Latence</span><span className="tile-value">{health?.vision ? `${fmtNum(health.vision.latency_ms)} ms` : '—'}</span></div>
          </div>
          {vision && (
            <p className="muted small">
              Image {vision.imgsz} px · confiance {fmtNum(vision.confidence, 2)} · masquage {vision.masking_detection ? 'surveillé' : 'non surveillé'}
            </p>
          )}
        </section>
        <section className="card">
          <h2 className="card-title">Détections récentes</h2>
          {alerts.length === 0 ? (
            <p className="muted">Aucune détection.</p>
          ) : (
            <ul className="incident-mini">
              {alerts.map((a) => (
                <li key={a.id}>
                  <LevelTag level={severityLevel(a.severity)} label={ALERT_TYPE[a.type]} />
                  <span className="muted nowrap">{fmtAgo(a.ts, now)}</span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </aside>
    </div>
  );
}
