import type {
  Alert, DeviceHealth, Mode, Scores, Severity, SiteConfig, SiteProfile, SystemHealth, Telemetry, WsMessage,
} from '../types';
import type { DataSource } from './source';

// Simulateur du mode démo : boîtier esp-01, Sentinel Brain et incidents, au format du contrat.
// Sert tant que l'API n'existe pas, et en secours le jour de la soutenance.

const DEVICE = 'esp-01';
const PERIOD_S = 2;
const HISTORY_S = 15 * 60;

const DEFAULT_PROFILE: SiteProfile = {
  site: { name: 'Micro-centrale démo EPSI', timezone: 'Europe/Paris' },
  devices: {
    [DEVICE]: {
      label: 'Boîtier entrée local technique',
      sensors: { dht11: true, mq2: true, pir: true, tamper: true },
      telemetry_period_s: 2,
      burst_period_ms: 500,
      burst_duration_s: 60,
      local_alarm: true,
      buzzer: true,
      tamper_sensitivity: 0.7,
      learning_minutes: 10,
    },
  },
  modes: {
    default: 'armed',
    schedule: [
      { days: ['mon', 'tue', 'wed', 'thu', 'fri'], from: '19:00', to: '07:00', profile: 'night' },
      { days: ['sat', 'sun'], from: '00:00', to: '23:59', profile: 'night' },
    ],
  },
  thresholds: {
    temp_c: { warning: 35, critical: 45 },
    hum_pct: { warning: 80, critical: 90 },
    gas_ratio: { warning: 1.3, critical: 1.8 },
  },
  brain: {
    sensitivity: { environment: 0.6, physical: 0.7, cyber: 0.8 },
    night_profile_boost: 0.15,
    window_s: 60,
    retrain_every_min: 30,
    forecast_horizon_min: 10,
    correlation_window_s: 5,
    loitering_s: 20,
    vision_confirm_s: 3,
    cooldown_s: 60,
  },
  vision: {
    enabled: true,
    imgsz: 320,
    confidence: 0.5,
    min_consecutive_frames: 3,
    zone: [[0.2, 0.25], [0.8, 0.25], [0.8, 0.95], [0.2, 0.95]],
    masking_detection: true,
    low_light_threshold: 35,
    face_recognition: true,
    face_threshold: 0.45,
    authorized_faces: [{ name: 'Michel' }, { name: 'Jeffrick' }],
  },
  integrations: { webhook_url: '', csv_export: true },
};

const SEVERITY_RANK: Record<Severity, number> = { info: 0, warning: 1, critical: 2 };
const clamp = (v: number, lo = 0, hi = 100) => Math.min(hi, Math.max(lo, v));
const noise = (a: number) => (Math.random() * 2 - 1) * a;
const round2 = (v: number) => Math.round(v * 100) / 100;
const nowS = () => Date.now() / 1000;
const pct = (v: number) => Math.round(v);

type NewAlert = Omit<Alert, 'id' | 'status' | 'count' | 'device_id' | 'ts'>;

export function createDemoSource(): DataSource {
  let config: SiteConfig = { version: 1, updated_at: nowS(), profile: structuredClone(DEFAULT_PROFILE) };
  const bootId = Math.random().toString(16).slice(2, 10);
  let seq = 0;
  const history: Telemetry[] = [];
  const scoreHistory: Scores[] = [];
  const alerts: Alert[] = [];
  const lastRaised: Record<string, number> = {};
  let nextAlertId = 1;
  let listener: ((m: WsMessage) => void) | null = null;
  const emit = (m: WsMessage) => listener?.(m);

  const st = {
    gas: 0, gasStart: 0,
    heat: 0, heatGas: 0, heatStart: 0,
    pirUntil: 0, pirTimes: [] as number[],
    tamperAt: -1e9, cyberAt: -1e9,
    offlineUntil: 0, wasOffline: false, buffered: [] as Telemetry[],
    mode: 'armed' as Mode,
    rssi: -58,
  };

  function sample(ts: number): Telemetry {
    if (st.gasStart) {
      const e = ts - st.gasStart;
      st.gas = e < 150 ? e * 0.0045 : Math.max(0, 0.675 - (e - 150) * 0.01);
      if (e > 230) st.gasStart = 0;
    }
    if (st.heatStart) {
      const e = ts - st.heatStart;
      const k = e < 120 ? e / 120 : Math.max(0, 1 - (e - 120) / 60);
      st.heat = 9 * k;
      st.heatGas = 0.25 * k;
      if (e > 180) st.heatStart = 0;
    }
    const temp = Math.round(22.3 + Math.sin(ts / 600) * 0.6 + st.heat + noise(0.12));
    const hum = Math.round(46.3 + Math.sin(ts / 900) * 2 + noise(0.1) - st.heat * 0.6);
    const ratio = round2(1 + Math.sin(ts / 420) * 0.015 + noise(0.004) + st.gas + st.heatGas);
    const pir = ts < st.pirUntil ? Math.random() < 0.8 : Math.random() < 0.008;
    if (pir) st.pirTimes.push(ts);
    st.pirTimes = st.pirTimes.filter((t) => t > ts - 60);
    const edge = clamp(Math.max(
      (ratio - 1) * 160,
      pir && st.mode === 'armed' ? 35 : 0,
      (temp - 30) * 6,
      ts - st.tamperAt < 20 ? 90 : 0,
    ));
    return {
      device_id: DEVICE, seq: ++seq, boot_id: bootId, ts,
      temp_c: temp, hum_pct: hum, gas_mv: Math.round(640 * ratio), gas_ratio: ratio, gas_do: ratio > 1.6,
      pir, pir_count: st.pirTimes.length, mode: st.mode, edge_score: Math.round(edge), replay: false,
    };
  }

  function scoresFor(t: Telemetry): Scores {
    const ts = t.ts;
    const env = clamp(6 + noise(2) + (t.gas_ratio - 1) * 170 + Math.max(0, t.temp_c - 27) * 8);
    const phys = clamp(4 + noise(2) + Math.min(t.pir_count * 5, 40) + (ts < st.pirUntil ? 50 : 0) + (ts - st.tamperAt < 60 ? 92 : 0));
    const cyber = clamp(3 + noise(1.5) + (ts - st.cyberAt < 120 ? 82 - (ts - st.cyberAt) * 0.5 : 0) + (st.wasOffline ? 40 : 0));
    return {
      ts, global: Math.round(Math.max(env, phys, cyber)),
      environment: Math.round(env), physical: Math.round(phys), cyber: Math.round(cyber),
    };
  }

  function raise(a: NewAlert, ts: number, cooldownS = 10) {
    if (ts - (lastRaised[a.type] ?? 0) < cooldownS) return;
    lastRaised[a.type] = ts;
    let alert = alerts.find((x) => x.type === a.type && x.status !== 'resolved');
    if (alert) {
      const severity = SEVERITY_RANK[a.severity] > SEVERITY_RANK[alert.severity] ? a.severity : alert.severity;
      Object.assign(alert, a, { severity, ts, count: alert.count + 1 });
    } else {
      alert = { ...a, id: nextAlertId++, status: 'open', count: 1, device_id: DEVICE, ts };
      alerts.push(alert);
    }
    emit({ type: 'alert', data: structuredClone(alert) });
  }

  function detect(t: Telemetry, s: Scores) {
    const th = config.profile.thresholds;
    const past = history.find((h) => h.ts >= t.ts - 60) ?? t;
    const slopePerMin = t.gas_ratio - past.gas_ratio;
    if (t.gas_ratio > 1.12 && slopePerMin > 0.02 && st.heat < 1) {
      const eta = slopePerMin > 0 ? Math.max(0, (th.gas_ratio.critical - t.gas_ratio) / slopePerMin) : null;
      raise({
        source: 'brain', domain: 'environment', type: 'gas_leak',
        severity: t.gas_ratio >= th.gas_ratio.warning ? 'critical' : 'warning',
        score: s.environment, eta_min: eta === null ? null : Math.round(eta * 10) / 10,
        explanation: `Gaz +${pct((t.gas_ratio - 1) * 100)} % au-dessus de la ligne de base, pente +${pct(slopePerMin * 100)} %/min, température stable.`,
        factors: [
          { name: 'gas_ratio', value: t.gas_ratio, contribution: 0.62 },
          { name: 'gas_slope', value: round2(slopePerMin), contribution: 0.3 },
          { name: 'temp_c', value: t.temp_c, contribution: 0.08 },
        ],
        details: { method: 'CUSUM + Holt' },
      }, t.ts);
    }
    if (t.temp_c >= 27 && t.gas_ratio > 1.06) {
      raise({
        source: 'brain', domain: 'environment', type: 'fire_risk', severity: 'critical',
        score: s.environment, eta_min: null,
        explanation: `Température +${t.temp_c - 22} °C et gaz +${pct((t.gas_ratio - 1) * 100)} % en même temps.`,
        factors: [
          { name: 'temp_c', value: t.temp_c, contribution: 0.48 },
          { name: 'gas_ratio', value: t.gas_ratio, contribution: 0.4 },
          { name: 'hum_pct', value: t.hum_pct, contribution: 0.12 },
        ],
        details: { rule: 'température et gaz corrélés' },
      }, t.ts);
    }
  }

  function deviceHealth(ts: number): DeviceHealth {
    return {
      device_id: DEVICE, ts, uptime_s: Math.round(ts - startedAt + 3600),
      heap_free: 182000 + Math.round(noise(4000)), psram_free: 7900000 - st.buffered.length * 120,
      rssi: Math.round(st.rssi + noise(2)), chip_temp_c: Math.round(41 + noise(1.5)),
      reset_reason: 'POWERON', buffer_len: st.buffered.length,
      wifi_disconnects: st.wasOffline ? 3 : 0, mqtt_reconnects: st.wasOffline ? 1 : 0, tls_errors: 0,
      fw_version: '0.1.0-demo',
    };
  }

  function tick() {
    const ts = nowS();
    const t = sample(ts);
    const s = scoresFor(t);
    if (ts < st.offlineUntil) {
      st.buffered.push({ ...t, replay: true });
    } else {
      if (st.buffered.length) {
        // Retour du réseau : statut en ligne puis rejeu du tampon PSRAM avec les horodatages d'origine
        emit({ type: 'status', data: { device_id: DEVICE, status: 'online', ts } });
        for (const b of st.buffered) {
          history.push(b);
          emit({ type: 'telemetry', data: b });
        }
        raise({
          source: 'brain', domain: 'cyber', type: 'jamming_suspected', severity: 'warning', score: s.cyber, eta_min: null,
          explanation: `Brouillage Wi-Fi présumé : RSSI -58 → -86 dBm puis 3 déconnexions ; ${st.buffered.length} mesures rejouées sans perte.`,
          factors: [
            { name: 'rssi_drop', value: -28, contribution: 0.55 },
            { name: 'wifi_disconnects', value: 3, contribution: 0.45 },
          ],
          details: { replayed: st.buffered.length },
        }, ts, 0);
        st.buffered = [];
        st.rssi = -58;
      }
      history.push(t);
      emit({ type: 'telemetry', data: t });
      detect(t, s);
    }
    while (history.length && history[0].ts < ts - HISTORY_S) history.shift();
    scoreHistory.push(s);
    while (scoreHistory.length && scoreHistory[0].ts < ts - HISTORY_S) scoreHistory.shift();
    emit({ type: 'score', data: s });
    if (seq % 5 === 0) emit({ type: 'health', data: deviceHealth(ts) });
  }

  // Quinze minutes d'historique au démarrage, et deux incidents passés pour la page Incidents
  const startedAt = nowS();
  for (let ts = startedAt - HISTORY_S; ts < startedAt; ts += PERIOD_S) {
    const t = sample(ts);
    history.push(t);
    scoreHistory.push(scoresFor(t));
  }
  alerts.push(
    {
      id: nextAlertId++, status: 'resolved', count: 1, device_id: DEVICE, source: 'brain', domain: 'maintenance',
      type: 'sensor_fault', severity: 'info', score: 12, eta_min: null, ts: startedAt - 840,
      explanation: 'Humidité figée à 46 % pendant 3 minutes : capteur DHT11 à vérifier.',
      factors: [{ name: 'hum_pct', value: 46, contribution: 1 }], details: {},
    },
    {
      id: nextAlertId++, status: 'acknowledged', count: 2, device_id: DEVICE, source: 'vision', domain: 'physical',
      type: 'intrusion_suspected', severity: 'warning', score: 48, eta_min: null, ts: startedAt - 420,
      explanation: 'Personne détectée par la caméra hors de la zone interdite, sans mouvement PIR.',
      factors: [{ name: 'vision_person', value: 1, contribution: 0.8 }, { name: 'pir', value: 0, contribution: 0.2 }],
      details: { presence_s: 6 },
    },
  );

  const scenarios = [
    { id: 'gas', label: 'Fuite de gaz' },
    { id: 'fire', label: 'Départ de feu' },
    { id: 'intrusion', label: 'Intrusion' },
    { id: 'tamper', label: 'Effraction' },
    { id: 'cyber', label: 'Attaque MQTT' },
    { id: 'jamming', label: 'Brouillage Wi-Fi' },
  ];

  return {
    kind: 'demo',
    scenarios,
    runScenario(id) {
      const ts = nowS();
      if (id === 'gas') st.gasStart = ts;
      if (id === 'fire') st.heatStart = ts;
      if (id === 'intrusion') {
        st.pirUntil = ts + 30;
        window.setTimeout(() => {
          const t = nowS();
          raise({
            source: 'brain', domain: 'physical', type: 'intrusion_confirmed', severity: 'critical', score: 88, eta_min: null,
            explanation: 'Mouvement PIR et personne dans la zone interdite à 1,2 s d\'écart.',
            factors: [
              { name: 'pir', value: 1, contribution: 0.45 },
              { name: 'vision_person_in_zone', value: 1, contribution: 0.45 },
              { name: 'schedule_night', value: 0, contribution: 0.1 },
            ],
            details: { zone: 'Zone interdite', presence_s: 4 },
          }, t, 0);
        }, 3000);
      }
      if (id === 'tamper') {
        st.tamperAt = ts;
        emit({ type: 'event', data: { device_id: DEVICE, seq: ++seq, boot_id: bootId, ts, type: 'tamper', value: 312, details: { threshold: 410 } } });
        raise({
          source: 'edge', domain: 'physical', type: 'sabotage', severity: 'critical', score: 92, eta_min: null,
          explanation: 'Effraction : main détectée sur le couvercle du boîtier (tactile 312, seuil 410).',
          factors: [{ name: 'tamper_touch', value: 312, contribution: 1 }],
          details: { sensor: 'T7' },
        }, ts, 0);
      }
      if (id === 'cyber') {
        st.cyberAt = ts;
        raise({
          source: 'brain', domain: 'cyber', type: 'cyber_attack', severity: 'warning', score: 82, eta_min: null,
          explanation: '14 connexions MQTT refusées en 30 s depuis 192.168.137.57 (client inconnu « probe-7 »).',
          factors: [
            { name: 'mqtt_denied_30s', value: 14, contribution: 0.7 },
            { name: 'unknown_client', value: 1, contribution: 0.3 },
          ],
          details: { source_ip: '192.168.137.57' },
        }, ts, 0);
      }
      if (id === 'jamming') {
        st.offlineUntil = ts + 24;
        st.wasOffline = true;
        st.rssi = -86;
        emit({ type: 'status', data: { device_id: DEVICE, status: 'offline', ts } });
      }
    },

    getAlerts: async () => structuredClone(alerts),
    async updateAlert(id, status) {
      const a = alerts.find((x) => x.id === id);
      if (!a) throw new Error(`Incident ${id} introuvable`);
      a.status = status;
      emit({ type: 'alert', data: structuredClone(a) });
      return structuredClone(a);
    },
    getTelemetry: async (deviceId, fromTs) => history.filter((t) => t.device_id === deviceId && t.ts >= fromTs),
    async sendCommand(deviceId, command) {
      await new Promise((r) => window.setTimeout(r, 250));
      const ts = nowS();
      if (command.cmd === 'mode') {
        st.mode = command.value;
        emit({ type: 'event', data: { device_id: deviceId, seq: ++seq, boot_id: bootId, ts, type: 'mode_change', value: command.value, details: {} } });
      }
      if (command.cmd === 'alarm') {
        emit({ type: 'event', data: { device_id: deviceId, seq: ++seq, boot_id: bootId, ts, type: 'edge_alarm', value: command.on, details: { manual: true } } });
      }
      if (command.cmd === 'reboot') {
        st.offlineUntil = ts + 8;
        emit({ type: 'status', data: { device_id: deviceId, status: 'offline', ts } });
      }
    },
    getConfig: async () => structuredClone(config),
    async putConfig(profile) {
      config = { version: config.version + 1, updated_at: nowS(), profile: structuredClone(profile) };
      return structuredClone(config);
    },
    getScore: async () => scoreHistory[scoreHistory.length - 1] ?? null,
    async getHealth(): Promise<SystemHealth> {
      const ts = nowS();
      return {
        ts,
        server: { cpu_pct: Math.round(24 + noise(6)), mem_pct: Math.round(47 + noise(2)), uptime_s: Math.round(ts - startedAt + 5400) },
        services: [
          { name: 'API', ok: true },
          { name: 'Mosquitto (MQTT)', ok: true },
          { name: 'PostgreSQL', ok: true },
          { name: 'Sentinel Brain', ok: true },
          { name: 'Vision', ok: true, detail: 'hors Docker, 127.0.0.1:8001' },
        ],
        vision: { fps: round2(14.6 + noise(0.6)), latency_ms: Math.round(62 + noise(6)) },
        devices: [deviceHealth(ts)],
      };
    },

    connect(onMessage, onState) {
      listener = onMessage;
      onState('connecting');
      const ready = window.setTimeout(() => {
        onState('online');
        for (const s of scoreHistory) onMessage({ type: 'score', data: s });
      }, 300);
      const timer = window.setInterval(tick, PERIOD_S * 1000);
      return () => {
        listener = null;
        window.clearTimeout(ready);
        window.clearInterval(timer);
      };
    },

    videoUrl: async () => null,
  };
}
