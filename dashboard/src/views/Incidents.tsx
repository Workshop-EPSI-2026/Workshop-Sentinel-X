import { useState } from 'react';
import { FactorBars } from '../components/FactorBars';
import { LevelTag } from '../components/StatusIcon';
import { ALERT_STATUS, ALERT_TYPE, DOMAIN, SEVERITY, fmtAgo, fmtDateTime, fmtNum, severityLevel } from '../format';
import { useApp, useNow } from '../state';
import type { Alert, AlertStatus, Domain, Severity } from '../types';

const SEV_ORDER: Record<Severity, number> = { critical: 0, warning: 1, info: 2 };

export function Incidents() {
  const { state } = useApp();
  const now = useNow(5000);
  const [status, setStatus] = useState<AlertStatus | 'active' | 'all'>('active');
  const [domain, setDomain] = useState<Domain | 'all'>('all');
  const [severity, setSeverity] = useState<Severity | 'all'>('all');

  const list = state.alerts
    .filter((a) => (status === 'all' || a.status === status || (status === 'active' && a.status !== 'resolved')) && (domain === 'all' || a.domain === domain) && (severity === 'all' || a.severity === severity))
    .sort((a, b) => SEV_ORDER[a.severity] - SEV_ORDER[b.severity] || b.ts - a.ts);

  const count = (s: AlertStatus) => state.alerts.filter((a) => a.status === s).length;

  return (
    <div className="view">
      <div className="filters" role="group" aria-label="Filtres des incidents">
        <label>
          Statut
          <select value={status} onChange={(e) => setStatus(e.target.value as AlertStatus | 'active' | 'all')}>
            <option value="active">À traiter ({count('open') + count('acknowledged')})</option>
            <option value="open">Ouverts ({count('open')})</option>
            <option value="acknowledged">Acquittés ({count('acknowledged')})</option>
            <option value="resolved">Résolus ({count('resolved')})</option>
            <option value="all">Tous ({state.alerts.length})</option>
          </select>
        </label>
        <label>
          Domaine
          <select value={domain} onChange={(e) => setDomain(e.target.value as Domain | 'all')}>
            <option value="all">Tous</option>
            {(Object.keys(DOMAIN) as Domain[]).map((d) => <option key={d} value={d}>{DOMAIN[d]}</option>)}
          </select>
        </label>
        <label>
          Gravité
          <select value={severity} onChange={(e) => setSeverity(e.target.value as Severity | 'all')}>
            <option value="all">Toutes</option>
            {(Object.keys(SEVERITY) as Severity[]).map((s) => <option key={s} value={s}>{SEVERITY[s]}</option>)}
          </select>
        </label>
      </div>

      {list.length === 0 ? (
        <p className="card muted">Aucun incident pour ces filtres.</p>
      ) : (
        <ul className="incident-list">
          {list.map((a) => <IncidentCard key={a.id} alert={a} now={now} />)}
        </ul>
      )}
    </div>
  );
}

function IncidentCard({ alert: a, now }: { alert: Alert; now: number }) {
  const { source, dispatch } = useApp();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function update(status: 'acknowledged' | 'resolved') {
    setBusy(true);
    setError(null);
    try {
      dispatch({ type: 'alert', data: await source.updateAlert(a.id, status) });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className={`card incident incident-${a.status}`}>
      <div className="incident-head">
        <LevelTag level={severityLevel(a.severity)} label={SEVERITY[a.severity]} />
        <h3>{ALERT_TYPE[a.type] ?? a.type}</h3>
        <span className="chip">{DOMAIN[a.domain]}</span>
        <span className="chip">{ALERT_STATUS[a.status]}</span>
        {a.count > 1 && <span className="chip">× {a.count}</span>}
        <span className="muted small push">{a.device_id} · {a.source} · {fmtDateTime(a.ts)} ({fmtAgo(a.ts, now)})</span>
      </div>

      <p className="incident-explanation">{a.explanation}</p>

      <div className="incident-body">
        <FactorBars factors={a.factors} />
        <dl className="incident-facts">
          <div><dt>Score</dt><dd>{fmtNum(a.score)}</dd></div>
          {a.eta_min !== null && (
            <div><dt>Niveau critique</dt><dd>{a.eta_min <= 0 ? 'atteint' : `dans ${fmtNum(a.eta_min, 1)} min`}</dd></div>
          )}
        </dl>
      </div>

      {a.status !== 'resolved' && (
        <div className="incident-actions">
          {a.status === 'open' && <button type="button" className="btn" disabled={busy} onClick={() => update('acknowledged')}>Acquitter</button>}
          <button type="button" className="btn" disabled={busy} onClick={() => update('resolved')}>Résoudre</button>
          {error && <span className="error small" role="alert">{error}</span>}
        </div>
      )}
    </li>
  );
}
