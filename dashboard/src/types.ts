// Types du contrat d'interface (docs/contracts.md). Horodatages : secondes Unix (UTC).

export type Mode = 'learning' | 'armed' | 'maintenance';

export interface Telemetry {
  device_id: string;
  seq: number;
  boot_id: string;
  ts: number;
  temp_c: number;
  hum_pct: number;
  gas_mv: number;
  gas_ratio: number;
  gas_do: boolean;
  pir: boolean;
  pir_count: number;
  mode: Mode;
  edge_score: number;
  replay: boolean;
}

export type EventType = 'pir' | 'tamper' | 'gas_do' | 'edge_alarm' | 'boot' | 'mode_change';

export interface DeviceEvent {
  device_id: string;
  seq: number;
  boot_id: string;
  ts: number;
  type: EventType;
  value: unknown;
  details: Record<string, unknown>;
}

export interface DeviceHealth {
  device_id: string;
  ts: number;
  uptime_s: number;
  heap_free: number;
  psram_free: number;
  rssi: number;
  chip_temp_c: number;
  reset_reason: string;
  buffer_len: number;
  wifi_disconnects: number;
  mqtt_reconnects: number;
  tls_errors: number;
  fw_version: string;
}

export interface DeviceStatus {
  device_id: string;
  status: 'online' | 'offline';
  ts: number;
}

export interface Scores {
  ts: number;
  global: number;
  environment: number;
  physical: number;
  cyber: number;
}

export type Domain = 'environment' | 'physical' | 'cyber' | 'maintenance';
export type Severity = 'info' | 'warning' | 'critical';
export type AlertStatus = 'open' | 'acknowledged' | 'resolved';
export type AlertType =
  | 'intrusion_confirmed'
  | 'intrusion_suspected'
  | 'loitering'
  | 'sabotage'
  | 'fire_risk'
  | 'gas_leak'
  | 'jamming_suspected'
  | 'cyber_attack'
  | 'sensor_fault'
  // Sentinel Brain v3 : badges et horaires, dérive, combinaison inhabituelle, état de la caméra
  | 'presence_authorized'
  | 'presence_to_verify'
  | 'thermal_drift'
  | 'unusual_pattern'
  | 'camera_degraded';

export interface Factor {
  name: string;
  value: number | boolean | string | null; // Brain explique aussi par des états (tamper = true) ou des messages
  contribution: number;
}

// sentinel/<cam>/vision relayé par l'API (docs/contracts.md, section Vision)
export interface VisionPerson {
  track_id: number;
  in_zone: boolean;
  dwell_s: number;
  badge: number | null;
  face?: string | null;       // visage reconnu (galerie locale du service vision)
  face_score?: number | null;
  authorized: boolean;
}

export interface VisionState {
  device_id: string;
  ts: number;
  fps: number;
  masked: boolean;
  low_light: boolean;
  frozen: boolean;
  zone_count: number;
  persons: VisionPerson[];
}

export interface Alert {
  id: number;
  status: AlertStatus;
  count: number;
  device_id: string;
  source: 'vision' | 'brain' | 'edge';
  domain: Domain;
  type: AlertType;
  severity: Severity;
  score: number;
  eta_min: number | null;
  ts: number;
  explanation: string;
  factors: Factor[];
  details: Record<string, unknown>;
}

export interface ServiceState {
  name: string;
  ok: boolean;
  detail?: string;
}

export interface SystemHealth {
  ts: number;
  server: { cpu_pct: number; mem_pct: number; uptime_s: number };
  services: ServiceState[];
  vision: { fps: number; latency_ms: number } | null;
  devices: DeviceHealth[];
}

export interface DeviceProfile {
  label: string;
  sensors: { dht11: boolean; mq2: boolean; pir: boolean; tamper: boolean };
  telemetry_period_s: number;
  burst_period_ms: number;
  burst_duration_s: number;
  local_alarm: boolean;
  buzzer: boolean;
  tamper_sensitivity: number;
  learning_minutes: number;
}

export type ThresholdKey = 'temp_c' | 'hum_pct' | 'gas_ratio';
export type SensitivityKey = 'environment' | 'physical' | 'cyber';

// Profil de site : même structure que config/site.example.yml
export interface SiteProfile {
  site: { name: string; timezone: string };
  devices: Record<string, DeviceProfile>;
  modes: {
    default: 'armed' | 'maintenance';
    schedule: { days: string[]; from: string; to: string; profile: string }[];
  };
  thresholds: Record<ThresholdKey, { warning: number; critical: number }>;
  brain: {
    sensitivity: Record<SensitivityKey, number>;
    night_profile_boost: number;
    window_s: number;
    retrain_every_min: number;
    forecast_horizon_min: number;
    correlation_window_s: number;
    loitering_s: number;
    vision_confirm_s?: number;
    cooldown_s: number;
  };
  vision: {
    enabled: boolean;
    imgsz: number;
    confidence: number;
    min_consecutive_frames: number;
    zone: [number, number][];
    masking_detection: boolean;
    low_light_threshold: number;
    face_recognition?: boolean;
    face_threshold?: number;
    authorized_faces?: { name: string; hours?: string; days?: string[] }[];
  };
  integrations: { webhook_url: string; csv_export: boolean };
}

export interface SiteConfig {
  version: number;
  updated_at: number;
  profile: SiteProfile;
}

export type Command =
  | { cmd: 'alarm'; on: boolean }
  | { cmd: 'led'; color: string }
  | { cmd: 'mode'; value: Mode }
  | { cmd: 'recalibrate' }
  | { cmd: 'reboot' };

// Messages poussés par l'API sur /ws
export type WsMessage =
  | { type: 'telemetry'; data: Telemetry }
  | { type: 'event'; data: DeviceEvent }
  | { type: 'health'; data: DeviceHealth }
  | { type: 'status'; data: DeviceStatus }
  | { type: 'score'; data: Scores }
  | { type: 'alert'; data: Alert }
  | { type: 'vision'; data: VisionState };
