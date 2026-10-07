import { createContext, useContext, useEffect, useReducer, type ReactNode } from 'react';
import { AuthError, type DataSource, type LinkState } from './api/source';
import type { Alert, DeviceEvent, DeviceHealth, DeviceStatus, Scores, SiteConfig, Telemetry, VisionState, WsMessage } from './types';

export const WINDOW_S = 15 * 60; // fenêtre affichée et conservée en mémoire

export interface State {
  link: LinkState;
  loadError: string | null;
  config: SiteConfig | null;
  telemetry: Record<string, Telemetry[]>;
  health: Record<string, DeviceHealth>;
  status: Record<string, DeviceStatus>;
  scores: Scores[];
  alerts: Alert[];
  lastEvent: DeviceEvent | null;
  vision: Record<string, VisionState>;
}

export type Action =
  | { type: 'link'; link: LinkState }
  | { type: 'loadError'; message: string | null }
  | { type: 'config'; config: SiteConfig }
  | { type: 'alerts'; alerts: Alert[] }
  | { type: 'history'; deviceId: string; items: Telemetry[] }
  | WsMessage;

export const initial: State = {
  link: 'connecting', loadError: null, config: null, telemetry: {}, health: {}, status: {}, scores: [], alerts: [], lastEvent: null, vision: {},
};

function trim<T extends { ts: number }>(items: T[]): T[] {
  if (!items.length) return items;
  const from = items[items.length - 1].ts - WINDOW_S;
  let i = 0;
  while (i < items.length && items[i].ts < from) i++;
  return i ? items.slice(i) : items;
}

function addTelemetry(list: Telemetry[], t: Telemetry): Telemetry[] {
  // Une mesure rejouée depuis le tampon peut être plus ancienne que la dernière reçue : insertion triée, sans doublon
  if (list.some((x) => x.boot_id === t.boot_id && x.seq === t.seq)) return list;
  const next = [...list, t];
  if (list.length && t.ts < list[list.length - 1].ts) next.sort((a, b) => a.ts - b.ts);
  return trim(next);
}

export function reducer(s: State, a: Action): State {
  switch (a.type) {
    case 'link':
      return { ...s, link: a.link };
    case 'loadError':
      return { ...s, loadError: a.message };
    case 'config':
      return { ...s, config: a.config };
    case 'alerts':
      return { ...s, alerts: a.alerts };
    case 'history': {
      const merged = [...a.items, ...(s.telemetry[a.deviceId] ?? [])].sort((x, y) => x.ts - y.ts);
      const unique = merged.filter((t, i) => i === 0 || !(t.seq === merged[i - 1].seq && t.boot_id === merged[i - 1].boot_id));
      return { ...s, telemetry: { ...s.telemetry, [a.deviceId]: trim(unique) } };
    }
    case 'telemetry': {
      const id = a.data.device_id;
      return { ...s, telemetry: { ...s.telemetry, [id]: addTelemetry(s.telemetry[id] ?? [], a.data) } };
    }
    case 'health':
      return { ...s, health: { ...s.health, [a.data.device_id]: a.data } };
    case 'status':
      return { ...s, status: { ...s.status, [a.data.device_id]: a.data } };
    case 'score': {
      const list = s.scores;
      if (list.length && a.data.ts <= list[list.length - 1].ts) {
        // Historique reçu après la valeur courante : insertion triée, sans doublon
        if (list.some((x) => x.ts === a.data.ts)) return s;
        return { ...s, scores: trim([...list, a.data].sort((x, y) => x.ts - y.ts)) };
      }
      return { ...s, scores: trim([...list, a.data]) };
    }
    case 'alert': {
      const i = s.alerts.findIndex((x) => x.id === a.data.id);
      const alerts = i < 0 ? [a.data, ...s.alerts] : s.alerts.map((x, j) => (j === i ? a.data : x));
      return { ...s, alerts };
    }
    case 'event':
      return { ...s, lastEvent: a.data };
    case 'vision':
      return { ...s, vision: { ...s.vision, [a.data.device_id]: a.data } };
    default:
      return s; // type de message inconnu (API plus récente que le dashboard) : ignoré, jamais d'écran blanc
  }
}

interface Ctx {
  state: State;
  source: DataSource;
  dispatch: (a: Action) => void;
}

const AppContext = createContext<Ctx | null>(null);

export function AppProvider({ source, onAuthError, children }: { source: DataSource; onAuthError: () => void; children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initial);

  useEffect(() => {
    let cancelled = false;
    const fail = (e: unknown) => {
      if (cancelled) return;
      if (e instanceof AuthError) onAuthError();
      else dispatch({ type: 'loadError', message: e instanceof Error ? e.message : String(e) });
    };

    (async () => {
      try {
        const [config, alerts, score] = await Promise.all([source.getConfig(), source.getAlerts(), source.getScore()]);
        if (cancelled) return;
        dispatch({ type: 'config', config });
        dispatch({ type: 'alerts', alerts });
        if (score) dispatch({ type: 'score', data: score });
        const from = Date.now() / 1000 - WINDOW_S;
        for (const id of Object.keys(config.profile.devices)) {
          const items = await source.getTelemetry(id, from);
          if (!cancelled) dispatch({ type: 'history', deviceId: id, items });
        }
        if (!cancelled) dispatch({ type: 'loadError', message: null });
      } catch (e) {
        fail(e);
      }
    })();

    const disconnect = source.connect(
      (m) => dispatch(m),
      (link) => dispatch({ type: 'link', link }),
    );
    return () => {
      cancelled = true;
      disconnect();
    };
  }, [source, onAuthError]);

  return <AppContext.Provider value={{ state, source, dispatch }}>{children}</AppContext.Provider>;
}

export function useApp(): Ctx {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error('useApp hors de AppProvider');
  return ctx;
}

// Boîtiers connus : ceux du profil de site, plus ceux qui publient sans y figurer
export function useDevices(): { id: string; label: string }[] {
  const { state } = useApp();
  const profile = state.config?.profile.devices ?? {};
  const ids = new Set([...Object.keys(profile), ...Object.keys(state.telemetry)]);
  return [...ids].sort().map((id) => ({ id, label: profile[id]?.label ?? id }));
}

// Horloge partagée pour les « il y a N s » et l'état hors ligne
export function useNow(periodMs = 1000): number {
  const [now, setNow] = useReducer((_: number, v: number) => v, Date.now() / 1000);
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now() / 1000), periodMs);
    return () => window.clearInterval(t);
  }, [periodMs]);
  return now;
}
