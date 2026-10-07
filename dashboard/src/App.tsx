import { useCallback, useEffect, useMemo, useState } from 'react';
import { createDemoSource } from './api/demo';
import { createLiveSource } from './api/live';
import { LevelTag } from './components/StatusIcon';
import { AppProvider, useApp } from './state';
import { Incidents } from './views/Incidents';
import { Login } from './views/Login';
import { Reglages } from './views/Reglages';
import { Supervision } from './views/Supervision';
import { Systeme } from './views/Systeme';
import { Vision } from './views/Vision';

type Session = { kind: 'demo' } | { kind: 'live'; token: string };

// Le jeton vit dans sessionStorage : il disparaît à la fermeture de l'onglet
function readSession(): Session | null {
  if (new URLSearchParams(location.search).has('demo')) return { kind: 'demo' }; // lien direct : /?demo
  try {
    const raw = sessionStorage.getItem('snx-session');
    return raw ? (JSON.parse(raw) as Session) : null;
  } catch {
    return null;
  }
}

function writeSession(s: Session | null) {
  try {
    if (s) sessionStorage.setItem('snx-session', JSON.stringify(s));
    else sessionStorage.removeItem('snx-session');
  } catch {
    /* stockage indisponible : la session ne survivra pas au rechargement */
  }
}

const VIEWS = [
  { id: 'supervision', label: 'Supervision', component: Supervision },
  { id: 'incidents', label: 'Incidents', component: Incidents },
  { id: 'vision', label: 'Vision', component: Vision },
  { id: 'systeme', label: 'Système', component: Systeme },
  { id: 'reglages', label: 'Réglages', component: Reglages },
] as const;

function useHashView() {
  const read = () => location.hash.replace(/^#\/?/, '') || 'supervision';
  const [view, setView] = useState(read);
  useEffect(() => {
    const on = () => setView(read());
    window.addEventListener('hashchange', on);
    return () => window.removeEventListener('hashchange', on);
  }, []);
  return view;
}

type Theme = 'auto' | 'light' | 'dark';

function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(() => {
    try {
      return (localStorage.getItem('snx-theme') as Theme) || 'auto';
    } catch {
      return 'auto';
    }
  });
  useEffect(() => {
    if (theme === 'auto') document.documentElement.removeAttribute('data-theme');
    else document.documentElement.setAttribute('data-theme', theme);
    try {
      localStorage.setItem('snx-theme', theme);
    } catch {
      /* préférence non mémorisée */
    }
  }, [theme]);
  const next = () => setTheme((t) => (t === 'auto' ? 'light' : t === 'light' ? 'dark' : 'auto'));
  return [theme, next];
}

export function App() {
  const [session, setSession] = useState<Session | null>(readSession);
  const [authError, setAuthError] = useState<string | null>(null);
  const source = useMemo(() => (session ? (session.kind === 'demo' ? createDemoSource() : createLiveSource(session.token)) : null), [session]);

  const logout = useCallback((error: string | null = null) => {
    writeSession(null);
    setSession(null);
    setAuthError(error);
  }, []);
  const onAuthError = useCallback(() => logout('Jeton opérateur refusé par l\'API.'), [logout]);

  if (!session || !source) {
    return (
      <Login
        error={authError}
        onToken={(token) => { const s: Session = { kind: 'live', token }; writeSession(s); setSession(s); setAuthError(null); }}
        onDemo={() => { const s: Session = { kind: 'demo' }; writeSession(s); setSession(s); setAuthError(null); }}
      />
    );
  }

  return (
    <AppProvider source={source} onAuthError={onAuthError}>
      <Shell onLogout={() => logout()} />
    </AppProvider>
  );
}

function Shell({ onLogout }: { onLogout: () => void }) {
  const { state, source } = useApp();
  const view = useHashView();
  const [theme, nextTheme] = useTheme();
  const current = VIEWS.find((v) => v.id === view) ?? VIEWS[0];
  const View = current.component;
  const open = state.alerts.filter((a) => a.status === 'open').length;
  // Lien de démo scripté : /?demo&scenario=gas lance un scénario au chargement
  useEffect(() => {
    const id = new URLSearchParams(location.search).get('scenario');
    if (id && source.runScenario) source.runScenario(id);
  }, [source]);

  const linkLabel = { online: 'Temps réel connecté', connecting: 'Connexion…', offline: 'Temps réel coupé' }[state.link];

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-name">Sentinel-X</span>
          <span className="muted small">{state.config?.profile.site.name ?? 'AetherCorp'}</span>
        </div>
        <div className="topbar-right">
          {source.kind === 'demo' && <span className="chip demo">Mode démo</span>}
          <LevelTag level={state.link === 'online' ? 'good' : state.link === 'connecting' ? 'warning' : 'critical'} label={linkLabel} />
          <button type="button" className="link-btn" onClick={nextTheme} title="Changer de thème">
            Thème : {theme === 'auto' ? 'auto' : theme === 'light' ? 'clair' : 'sombre'}
          </button>
          <button type="button" className="link-btn" onClick={onLogout}>Déconnexion</button>
        </div>
      </header>

      <nav className="tabs" aria-label="Vues">
        {VIEWS.map((v) => (
          <a key={v.id} href={`#/${v.id}`} className={v.id === current.id ? 'tab active' : 'tab'} aria-current={v.id === current.id ? 'page' : undefined}>
            {v.label}
            {v.id === 'incidents' && open > 0 && <span className="badge" aria-label={`${open} ouverts`}>{open}</span>}
          </a>
        ))}
      </nav>

      {source.scenarios && (
        <div className="scenarios" role="group" aria-label="Scénarios de démonstration">
          <span className="muted small">Scénarios :</span>
          {source.scenarios.map((s) => (
            <button key={s.id} type="button" className="btn small" onClick={() => source.runScenario?.(s.id)}>{s.label}</button>
          ))}
        </div>
      )}

      {state.loadError && <p className="banner error" role="alert">Chargement incomplet : {state.loadError}</p>}

      <main className="content">
        <View />
      </main>
    </div>
  );
}
