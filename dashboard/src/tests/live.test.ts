// Client de l'API réelle : où part le jeton opérateur, et ce qui se passe quand il est refusé.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createLiveSource } from '../api/live';
import { AuthError } from '../api/source';

const TOKEN = 'jeton-de-test-' + 'x'.repeat(30);

function mockFetch(status: number, body: unknown = {}) {
  const fn = vi.fn(async () => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));
  vi.stubGlobal('fetch', fn);
  return fn;
}

afterEach(() => vi.unstubAllGlobals());

describe('requêtes REST', () => {
  it('envoie le jeton dans l’en-tête Authorization, jamais dans l’URL', async () => {
    const fetch = mockFetch(200, []);
    await createLiveSource(TOKEN).getAlerts();
    const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).not.toContain(TOKEN);
    expect((init.headers as Record<string, string>).Authorization).toBe(`Bearer ${TOKEN}`);
  });

  it('signale un jeton refusé (401) pour renvoyer à l’écran de connexion', async () => {
    mockFetch(401, { detail: 'Authentification requise' });
    await expect(createLiveSource(TOKEN).getConfig()).rejects.toBeInstanceOf(AuthError);
  });

  it('remonte les autres erreurs sans les confondre avec un refus', async () => {
    mockFetch(503, { detail: 'broker indisponible' });
    const p = createLiveSource(TOKEN).sendCommand('esp-01', { cmd: 'reboot' });
    await expect(p).rejects.not.toBeInstanceOf(AuthError);
    await expect(p).rejects.toThrow(/503/);
  });
});

describe('flux vidéo', () => {
  it('utilise un ticket court délivré par l’API, pas le jeton opérateur', async () => {
    const fetch = mockFetch(200, { ticket: '1791300060.abcdef', expires: 1791300060 });
    const url = await createLiveSource(TOKEN).videoUrl();
    expect(url).toBe('/video?ticket=1791300060.abcdef');
    expect(url).not.toContain(TOKEN);
    expect((fetch.mock.calls[0] as unknown as [string])[0]).toBe('/api/v1/video/ticket');
  });
});

describe('temps réel', () => {
  it('s’authentifie par le premier message WebSocket, sans jeton dans l’URL', () => {
    const sockets: { url: string; sent: string[]; onopen?: () => void; close: () => void; send: (m: string) => void }[] = [];
    class FakeWS {
      url: string;
      sent: string[] = [];
      onopen?: () => void;
      onmessage?: (e: { data: string }) => void;
      onclose?: () => void;
      constructor(url: string) {
        this.url = url;
        sockets.push(this);
      }
      send(m: string) {
        this.sent.push(m);
      }
      close() {}
    }
    vi.stubGlobal('WebSocket', FakeWS);
    vi.stubGlobal('location', { protocol: 'https:', host: '192.168.137.1' });
    vi.stubGlobal('window', { setTimeout, clearTimeout });
    const stop = createLiveSource(TOKEN).connect(() => {}, () => {});
    sockets[0].onopen?.();
    expect(sockets[0].url).toBe('wss://192.168.137.1/ws');
    expect(JSON.parse(sockets[0].sent[0])).toEqual({ type: 'auth', token: TOKEN });
    stop();
  });
});
