import { useEffect, useState } from 'react';
import { LevelTag } from '../components/StatusIcon';
import { ALERT_TYPE, fmtAgo, fmtNum, severityLevel, type Level } from '../format';
import { useApp, useNow } from '../state';
import type { SystemHealth } from '../types';

export function Vision() {
  const { state, source } = useApp();
  const now = useNow(5000);
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [videoError, setVideoError] = useState(false);
  const [url, setUrl] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const vision = state.config?.profile.vision;
  const alerts = state.alerts
    .filter((a) => a.source === 'vision' || a.device_id.startsWith('cam') || a.type.startsWith('intrusion') || a.type === 'loitering')
    .slice(0, 6);
  const cams = Object.values(state.vision);
  const cam = cams.length ? cams[0] : null;
  const live = cam !== null && now / 1000 - cam.ts < 10;
  const camState = !cam || !live ? 'Hors ligne' : cam.masked ? 'Caméra masquée' : cam.frozen ? 'Image figée' : cam.low_light ? 'Trop sombre (le PIR prend le relais)' : 'Scène visible';
  const camLevel: Level = !cam || !live || cam.masked || cam.frozen ? 'critical' : cam.low_light ? 'warning' : 'good';
  const inZone = cam ? cam.persons.filter((p) => p.in_zone) : [];
  const intruders = inZone.filter((p) => !p.authorized);

  // Nouveau ticket à chaque (re)connexion du flux : il n'ouvre le flux que pendant 60 s
  useEffect(() => {
    let alive = true;
    source.videoUrl().then((u) => alive && setUrl(u)).catch(() => alive && setVideoError(true));
    return () => {
      alive = false;
    };
  }, [source, attempt]);

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
              <p>{source.kind !== 'live' ? 'Pas de flux vidéo en mode démo.' : videoError ? 'Flux indisponible : vérifier que la vision tourne sur le PC serveur (tools\\demarrer.ps1).' : 'Connexion au flux…'}</p>
              {source.kind === 'live' && videoError && <button type="button" className="btn" onClick={() => { setVideoError(false); setUrl(null); setAttempt((n) => n + 1); }}>Réessayer</button>}
            </div>
          )}
        </div>
      </section>

      <aside className="vision-side">
        <section className="card">
          <h2 className="card-title">État en direct{cam ? ` · ${cam.device_id}` : ''}</h2>
          <p><LevelTag level={camLevel} label={camState} /></p>
          <div className="tiles two">
            <div className="tile"><span className="tile-label">Personnes vues</span><span className="tile-value">{cam && live ? cam.persons.length : '—'}</span></div>
            <div className="tile"><span className="tile-label">Dans la zone</span><span className="tile-value">{cam && live ? inZone.length : '—'}</span></div>
          </div>
          {live && inZone.length > 0 && (
            <ul className="incident-mini">
              {inZone.map((p) => (
                <li key={p.track_id}>
                  <LevelTag level={p.authorized ? 'good' : 'critical'} label={p.authorized ? `Badge ${p.badge} autorisé` : p.badge !== null ? `Badge ${p.badge} non autorisé` : 'Sans badge'} />
                  <span className="muted nowrap">#{p.track_id} · {Math.round(p.dwell_s)} s</span>
                </li>
              ))}
            </ul>
          )}
          {live && intruders.length > 0 && <p className="muted small">Brain confirme l'intrusion avec le PIR et les horaires des badges.</p>}
        </section>
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
