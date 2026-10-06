import type {
  Alert, AlertStatus, Command, Scores, SiteConfig, SiteProfile, SystemHealth, Telemetry, WsMessage,
} from '../types';

export type LinkState = 'connecting' | 'online' | 'offline';

export interface Scenario {
  id: string;
  label: string;
}

// Une source de données : l'API réelle (live) ou le simulateur (démo). Les vues ne voient que cette interface.
export interface DataSource {
  kind: 'live' | 'demo';
  getAlerts(): Promise<Alert[]>;
  updateAlert(id: number, status: Exclude<AlertStatus, 'open'>): Promise<Alert>;
  getTelemetry(deviceId: string, fromTs: number): Promise<Telemetry[]>;
  sendCommand(deviceId: string, command: Command): Promise<void>;
  getConfig(): Promise<SiteConfig>;
  putConfig(profile: SiteProfile): Promise<SiteConfig>;
  getScore(): Promise<Scores | null>;
  getHealth(): Promise<SystemHealth>;
  connect(onMessage: (m: WsMessage) => void, onState: (s: LinkState) => void): () => void;
  videoUrl(): string | null;
  scenarios?: Scenario[];
  runScenario?(id: string): void;
}

export class AuthError extends Error {}
