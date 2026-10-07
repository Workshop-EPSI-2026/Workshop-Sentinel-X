import { useEffect, useState, type ReactNode } from 'react';
import { DOMAIN, fmtDateTime, fmtNum } from '../format';
import { useApp } from '../state';
import type { SensitivityKey, SiteProfile, ThresholdKey } from '../types';

const THRESHOLDS: { key: ThresholdKey; label: string; unit: string; step: number }[] = [
  { key: 'temp_c', label: 'Température', unit: '°C', step: 1 },
  { key: 'hum_pct', label: 'Humidité', unit: '%', step: 1 },
  { key: 'gas_ratio', label: 'Gaz (ratio)', unit: '', step: 0.05 },
];

function validate(p: SiteProfile): string[] {
  const errors: string[] = [];
  for (const t of THRESHOLDS) {
    const th = p.thresholds[t.key];
    if (!(th.warning < th.critical)) errors.push(`${t.label} : l'avertissement doit être inférieur au seuil critique.`);
  }
  for (const [id, d] of Object.entries(p.devices)) {
    if (d.telemetry_period_s < 1) errors.push(`${id} : période d'envoi d'au moins 1 s (limite du DHT11).`);
  }
  if (p.vision.confidence < 0.1 || p.vision.confidence > 0.95) errors.push('Vision : confiance entre 0,10 et 0,95.');
  return errors;
}

export function Reglages() {
  const { state, source, dispatch } = useApp();
  const config = state.config;
  const [draft, setDraft] = useState<SiteProfile | null>(null);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    if (config && !draft) setDraft(structuredClone(config.profile));
  }, [config, draft]);

  if (!config || !draft) return <p className="card muted">Chargement du profil de site…</p>;

  const dirty = JSON.stringify(draft) !== JSON.stringify(config.profile);
  const errors = validate(draft);
  const edit = (fn: (p: SiteProfile) => void) =>
    setDraft((prev) => {
      const next = structuredClone(prev!);
      fn(next);
      return next;
    });

  async function save() {
    setSaving(true);
    setMessage(null);
    try {
      const saved = await source.putConfig(draft!);
      dispatch({ type: 'config', config: saved });
      setDraft(structuredClone(saved.profile));
      setMessage({ ok: true, text: `Version ${saved.version} enregistrée et publiée aux boîtiers et à Sentinel Brain.` });
    } catch (e) {
      setMessage({ ok: false, text: `Échec de l'enregistrement : ${e instanceof Error ? e.message : e}` });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="view settings">
      <div className="settings-bar card">
        <div>
          <h2 className="card-title">{draft.site.name}</h2>
          <p className="muted small">Profil version {config.version} · modifié le {fmtDateTime(config.updated_at)} · appliqué sans redémarrage</p>
        </div>
        <div className="settings-actions">
          <button type="button" className="btn" disabled={!dirty || saving} onClick={() => { setDraft(structuredClone(config.profile)); setMessage(null); }}>Annuler</button>
          <button type="button" className="btn primary" disabled={!dirty || saving || errors.length > 0} onClick={save}>{saving ? 'Enregistrement…' : 'Enregistrer'}</button>
        </div>
        {errors.length > 0 && <ul className="error small" role="alert">{errors.map((e) => <li key={e}>{e}</li>)}</ul>}
        {message && <p className={message.ok ? 'success small' : 'error small'} role="status">{message.text}</p>}
      </div>

      <Section title="Seuils absolus" hint="Garde-fous en plus de la détection adaptative de Sentinel Brain.">
        <table className="data-table form-table">
          <thead><tr><th>Mesure</th><th>Avertissement</th><th>Critique</th></tr></thead>
          <tbody>
            {THRESHOLDS.map((t) => (
              <tr key={t.key}>
                <td>{t.label}</td>
                {(['warning', 'critical'] as const).map((lvl) => (
                  <td key={lvl}>
                    <NumberInput
                      hideLabel
                      label={`${t.label} ${lvl === 'warning' ? 'avertissement' : 'critique'}`}
                      value={draft.thresholds[t.key][lvl]}
                      step={t.step}
                      unit={t.unit}
                      onChange={(v) => edit((p) => { p.thresholds[t.key][lvl] = v; })}
                    />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </Section>

      <Section title="Sensibilité de Sentinel Brain" hint="0 = tolérant, 1 = très sensible. La nuit, la sensibilité augmente du bonus indiqué.">
        {(['environment', 'physical', 'cyber'] as SensitivityKey[]).map((k) => (
          <Slider key={k} label={DOMAIN[k]} value={draft.brain.sensitivity[k]} onChange={(v) => edit((p) => { p.brain.sensitivity[k] = v; })} />
        ))}
        <Slider label="Bonus de nuit" value={draft.brain.night_profile_boost} max={0.5} onChange={(v) => edit((p) => { p.brain.night_profile_boost = v; })} />
        <div className="form-grid">
          <NumberInput label="Intrus confirmé sans PIR après (s ; 0 = PIR exigé)" value={draft.brain.vision_confirm_s ?? 3} step={1} onChange={(v) => edit((p) => { p.brain.vision_confirm_s = v; })} />
          <NumberInput label="Rôdeur après (s)" value={draft.brain.loitering_s} step={5} onChange={(v) => edit((p) => { p.brain.loitering_s = v; })} />
          <NumberInput label="Délai entre deux notifications (s)" value={draft.brain.cooldown_s} step={10} onChange={(v) => edit((p) => { p.brain.cooldown_s = v; })} />
          <NumberInput label="Horizon de prévision (min)" value={draft.brain.forecast_horizon_min} step={1} onChange={(v) => edit((p) => { p.brain.forecast_horizon_min = v; })} />
        </div>
      </Section>

      <Section title="Mode par défaut">
        <div className="radio-row" role="radiogroup" aria-label="Mode par défaut">
          {(['armed', 'maintenance'] as const).map((m) => (
            <label key={m} className="radio">
              <input type="radio" name="mode" checked={draft.modes.default === m} onChange={() => edit((p) => { p.modes.default = m; })} />
              {m === 'armed' ? 'Surveillance' : 'Maintenance (alarmes coupées)'}
            </label>
          ))}
        </div>
      </Section>

      {Object.entries(draft.devices).map(([id, d]) => (
        <Section key={id} title={`Boîtier ${id}`} hint={d.label}>
          <div className="form-grid">
            <NumberInput label="Période d'envoi (s)" value={d.telemetry_period_s} step={1} onChange={(v) => edit((p) => { p.devices[id].telemetry_period_s = v; })} />
            <NumberInput label="Apprentissage au démarrage (min)" value={d.learning_minutes} step={1} onChange={(v) => edit((p) => { p.devices[id].learning_minutes = v; })} />
          </div>
          <Slider label="Sensibilité de l'effraction tactile" value={d.tamper_sensitivity} onChange={(v) => edit((p) => { p.devices[id].tamper_sensitivity = v; })} />
          <div className="check-row">
            <Check label="Alarme locale (sans le serveur)" checked={d.local_alarm} onChange={(v) => edit((p) => { p.devices[id].local_alarm = v; })} />
            <Check label="Buzzer" checked={d.buzzer} onChange={(v) => edit((p) => { p.devices[id].buzzer = v; })} />
            {(Object.keys(d.sensors) as (keyof typeof d.sensors)[]).map((s) => (
              <Check key={s} label={`Capteur ${s.toUpperCase()}`} checked={d.sensors[s]} onChange={(v) => edit((p) => { p.devices[id].sensors[s] = v; })} />
            ))}
          </div>
        </Section>
      ))}

      <Section title="Vision" hint="La zone interdite se règle dans config/ (polygone normalisé).">
        <div className="check-row">
          <Check label="Vision active" checked={draft.vision.enabled} onChange={(v) => edit((p) => { p.vision.enabled = v; })} />
          <Check label="Détection de caméra masquée" checked={draft.vision.masking_detection} onChange={(v) => edit((p) => { p.vision.masking_detection = v; })} />
        </div>
        <Slider label="Confiance minimale" value={draft.vision.confidence} min={0.1} max={0.95} onChange={(v) => edit((p) => { p.vision.confidence = v; })} />
        <div className="form-grid">
          <NumberInput label="Seuil de faible luminosité (0-255)" value={draft.vision.low_light_threshold} step={5} onChange={(v) => edit((p) => { p.vision.low_light_threshold = v; })} />
        </div>
      </Section>
    </div>
  );
}

function Section({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <section className="card">
      <h2 className="card-title">{title}</h2>
      {hint && <p className="muted small">{hint}</p>}
      {children}
    </section>
  );
}

function NumberInput({ label, value, step, unit, hideLabel, onChange }: { label: string; value: number; step: number; unit?: string; hideLabel?: boolean; onChange: (v: number) => void }) {
  return (
    <label className="field">
      <span className={hideLabel ? 'sr-only' : 'field-label'}>{label}</span>
      <span className="field-input">
        <input type="number" value={value} step={step} onChange={(e) => e.target.value !== '' && onChange(Number(e.target.value))} />
        {unit && <span className="muted">{unit}</span>}
      </span>
    </label>
  );
}

function Slider({ label, value, min = 0, max = 1, onChange }: { label: string; value: number; min?: number; max?: number; onChange: (v: number) => void }) {
  return (
    <label className="slider">
      <span className="field-label">{label}</span>
      <input type="range" min={min} max={max} step={0.05} value={value} onChange={(e) => onChange(Number(e.target.value))} />
      <output className="slider-value">{fmtNum(value, 2)}</output>
    </label>
  );
}

function Check({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="check">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}
