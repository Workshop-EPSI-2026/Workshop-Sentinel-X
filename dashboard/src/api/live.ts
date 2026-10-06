import type { Alert, Scores, SiteConfig, SystemHealth, Telemetry, WsMessage } from '../types';
import { AuthError, type DataSource } from './source';

// Client de l'API réelle, même origine que le dashboard (servi par nginx) : pas de CORS.
export function createLiveSource(token: string): DataSource {
  async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
    const res = await fetch(path, {
      method,
      headers: {
        Authorization: `Bearer ${token}`,
        ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    if (res.status === 401 || res.status === 403) throw new AuthError('Jeton opérateur refusé');
    if (!res.ok) throw new Error(`${method} ${path} : HTTP ${res.status}`);
    if (res.status === 204) return undefined as T;
    return (await res.json()) as T;
  }

  return {
    kind: 'live',
    getAlerts: () => call<Alert[]>('GET', '/api/v1/alerts'),
    updateAlert: (id, status) => call<Alert>('PATCH', `/api/v1/alerts/${id}`, { status }),
    async getTelemetry(deviceId, fromTs) {
      const items: Telemetry[] = [];
      let from: number | null = fromTs;
      // Historique paginé : { items, next } ; quelques pages suffisent pour 15 minutes
      for (let page = 0; from !== null && page < 10; page++) {
        const q = new URLSearchParams({ device: deviceId, from: String(from) });
        const res: { items: Telemetry[]; next: number | null } = await call('GET', `/api/v1/telemetry?${q}`);
        items.push(...res.items);
        from = res.next;
      }
      return items;
    },
    sendCommand: (deviceId, command) => call<void>('POST', '/api/v1/commands', { device_id: deviceId, ...command }),
    getConfig: () => call<SiteConfig>('GET', '/api/v1/config'),
    putConfig: (profile) => call<SiteConfig>('PUT', '/api/v1/config', { profile }),
    getScore: () => call<Scores | null>('GET', '/api/v1/score'),
    getHealth: () => call<SystemHealth>('GET', '/api/v1/health'),

    connect(onMessage, onState) {
      let ws: WebSocket | null = null;
      let stopped = false;
      let delay = 1000;
      let timer: number | undefined;

      const open = () => {
        onState('connecting');
        const proto = location.protocol === 'https:' ? 'wss' : 'ws';
        ws = new WebSocket(`${proto}://${location.host}/ws`);
        // Le jeton part dans le premier message, jamais dans l'URL (qui finirait dans les journaux nginx)
        ws.onopen = () => ws?.send(JSON.stringify({ type: 'auth', token }));
        ws.onmessage = (e) => {
          let msg: { type?: string };
          try {
            msg = JSON.parse(String(e.data));
          } catch {
            return;
          }
          delay = 1000;
          onState('online');
          if (msg.type !== 'ready') onMessage(msg as WsMessage);
        };
        ws.onclose = () => {
          onState('offline');
          if (!stopped) {
            timer = window.setTimeout(open, delay);
            delay = Math.min(delay * 2, 15000);
          }
        };
      };

      open();
      return () => {
        stopped = true;
        window.clearTimeout(timer);
        ws?.close();
      };
    },

    videoUrl: () => `/video?token=${encodeURIComponent(token)}`,
  };
}
