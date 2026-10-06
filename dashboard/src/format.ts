import type { AlertStatus, AlertType, Domain, Mode, Severity, Telemetry, DeviceStatus } from './types';

export const fmtNum = (v: number, digits = 0) =>
  v.toLocaleString('fr-FR', { minimumFractionDigits: digits, maximumFractionDigits: digits });

export const fmtTime = (ts: number, withSeconds = true) =>
  new Date(ts * 1000).toLocaleTimeString('fr-FR', {
    hour: '2-digit', minute: '2-digit', ...(withSeconds ? { second: '2-digit' } : {}),
  });

export const fmtDateTime = (ts: number) =>
  new Date(ts * 1000).toLocaleString('fr-FR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' });

export function fmtAgo(ts: number, now = Date.now() / 1000) {
  const s = Math.max(0, Math.round(now - ts));
  if (s < 60) return `il y a ${s} s`;
  if (s < 3600) return `il y a ${Math.round(s / 60)} min`;
  return `il y a ${Math.round(s / 3600)} h`;
}

export function fmtDuration(s: number) {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return h ? `${h} h ${String(m).padStart(2, '0')}` : `${m} min`;
}

export const ALERT_TYPE: Record<AlertType, string> = {
  intrusion_confirmed: 'Intrusion confirmée',
  intrusion_suspected: 'Intrusion présumée',
  loitering: 'Rôdeur',
  sabotage: 'Sabotage',
  fire_risk: 'Risque incendie',
  gas_leak: 'Fuite de gaz',
  jamming_suspected: 'Brouillage Wi-Fi présumé',
  cyber_attack: 'Attaque cyber',
  sensor_fault: 'Capteur défaillant',
  presence_authorized: 'Présence autorisée',
  presence_to_verify: 'Présence à vérifier',
  thermal_drift: 'Dérive thermique',
  unusual_pattern: 'Combinaison inhabituelle',
  camera_degraded: 'Caméra dégradée',
};

export const DOMAIN: Record<Domain, string> = {
  environment: 'Environnement',
  physical: 'Physique',
  cyber: 'Cyber',
  maintenance: 'Maintenance',
};

export const SEVERITY: Record<Severity, string> = { info: 'Info', warning: 'Avertissement', critical: 'Critique' };
export const ALERT_STATUS: Record<AlertStatus, string> = { open: 'Ouvert', acknowledged: 'Acquitté', resolved: 'Résolu' };
export const MODE: Record<Mode, string> = { learning: 'Apprentissage', armed: 'Surveillance', maintenance: 'Maintenance' };

export const FACTOR: Record<string, string> = {
  gas_ratio: 'Ratio gaz',
  gas_slope: 'Pente du gaz (/min)',
  temp_c: 'Température (°C)',
  hum_pct: 'Humidité (%)',
  pir: 'Mouvement PIR',
  vision_person: 'Personne (caméra)',
  vision_person_in_zone: 'Personne dans la zone',
  schedule_night: 'Plage de nuit',
  tamper_touch: 'Effraction tactile',
  mqtt_denied_30s: 'Accès MQTT refusés (30 s)',
  unknown_client: 'Client inconnu',
  rssi_drop: 'Chute du RSSI (dBm)',
  wifi_disconnects: 'Déconnexions Wi-Fi',
};

// Niveaux de score (0-100), partagés par la jauge, les tuiles et les graphiques
export type Level = 'good' | 'warning' | 'serious' | 'critical';
export const LEVEL_LABEL: Record<Level, string> = { good: 'Normal', warning: 'Vigilance', serious: 'Alerte', critical: 'Critique' };
export const SCORE_STEPS = { warning: 40, serious: 60, critical: 80 };

export function scoreLevel(score: number): Level {
  if (score >= SCORE_STEPS.critical) return 'critical';
  if (score >= SCORE_STEPS.serious) return 'serious';
  if (score >= SCORE_STEPS.warning) return 'warning';
  return 'good';
}

export const severityLevel = (s: Severity): Level => (s === 'critical' ? 'critical' : s === 'warning' ? 'warning' : 'good');

// Voyant du boîtier, mêmes couleurs que la LED RGB de l'ESP32-S3 (docs/architecture.md)
export function deviceLed(t: Telemetry | undefined, status: DeviceStatus | undefined, now = Date.now() / 1000) {
  if (!t || status?.status === 'offline' || now - t.ts > 15) return { color: 'var(--led-violet)', label: 'Hors ligne' };
  if (t.mode === 'maintenance') return { color: 'var(--led-white)', label: 'Maintenance' };
  if (t.mode === 'learning') return { color: 'var(--led-blue)', label: 'Apprentissage' };
  if (t.edge_score >= 70) return { color: 'var(--led-red)', label: 'Alarme' };
  if (t.edge_score >= 40) return { color: 'var(--led-orange)', label: 'Suspicion' };
  return { color: 'var(--led-green)', label: 'Surveillance' };
}
