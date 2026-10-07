"""Sentinel Brain : les 4 couches + fusion avec la vision + incidents expliqués.

Utilisation (identique dans le notebook, les tests et le service MQTT app/main.py) :

    brain = SentinelBrain.from_profile(profil)          # profil de site (dict YAML)
    for out in brain.handle(topic, payload, rx_ts):      # chaque message MQTT reçu
        out["kind"] == "score"  -> publier out["payload"] sur sentinel/brain/score
        out["kind"] == "alert"  -> POST /api/v1/alerts avec out["payload"]
    brain.tick(now)                                      # toutes les 2 s : caméra muette, rafales d'accès refusés
    brain.security_event(raison, ip, now)                # ligne « accès refusé » du journal de Mosquitto
"""
from __future__ import annotations

import json
import math
from collections import deque
from dataclasses import dataclass, field

from .config import CALIBRATION, BrainConfig
from .detectors import Holt, PoissonRate, RateOfRise, RobustCusum
from .multivariate import MultivariateDetector, window_features
from .quality import DataQuality, QualityResult
from .site import BrokerWatch, CameraBrain, Person, SitePolicy

DOMAIN_OF = {"gas_leak": "environment", "fire_risk": "environment", "thermal_drift": "environment",
             "unusual_pattern": "environment", "intrusion_suspected": "physical", "intrusion_confirmed": "physical",
             "loitering": "physical", "presence_authorized": "physical", "presence_to_verify": "physical",
             "sabotage": "physical", "cyber_attack": "cyber", "jamming_suspected": "cyber",
             "sensor_fault": "maintenance", "camera_degraded": "maintenance"}
SEVERITY_RANK = {"info": 0, "warning": 1, "critical": 2}
# Un incident ouvert absorbe ses suites de même famille, sauf si la situation s'aggrave.
ENV_RANK = {"unusual_pattern": 0, "thermal_drift": 1, "gas_leak": 2, "fire_risk": 3}
PERSON_RANK = {"presence_authorized": 0, "presence_to_verify": 1, "intrusion_suspected": 2, "intrusion_confirmed": 3}
CAMERA_SCORE = {"intrusion_confirmed": 100.0, "sabotage": 100.0, "loitering": 75.0, "intrusion_suspected": 70.0,
                "presence_to_verify": 50.0, "presence_authorized": 10.0}


def _fmt(x: float, nd: int = 1) -> str:
    """Nombre à la française : 1,8 et non 1.8."""
    return f"{x:.{nd}f}".replace(".", ",")


def _decay(since_s: float | None, full_s: float, fade_s: float) -> float:
    """100 pendant full_s secondes, puis décroissance linéaire jusqu'à 0 en fade_s secondes."""
    if since_s is None or since_s < 0:
        return 0.0
    if since_s <= full_s:
        return 100.0
    return max(0.0, 100.0 * (1.0 - (since_s - full_s) / fade_s))


def _cusum(name: str, sens: float, direction: str, **extra) -> RobustCusum:
    c = CALIBRATION[name]
    return RobustCusum(name, k=c["k"], h=c["h"] * BrainConfig.h_scale(sens), tau_d=c["tau_d"],
                       min_sigma=c["min_sigma"], direction=direction, **extra)


@dataclass
class Incident:
    type: str
    severity: str
    opened_ts: float
    last_true_rx: float
    emitted_severity: str | None = None
    false_since: float | None = None


@dataclass
class DeviceBrain:
    """État d'un boîtier ESP32-S3 : un jeu de détecteurs par boîtier, mémoire bornée."""
    cfg: BrainConfig
    seed: int = 42
    device: str = ""
    first_ts: float | None = None
    temp_s: float | None = None
    last_t: float | None = None
    window: deque = field(default_factory=deque)
    last_feat_t: float = -1e18
    mv_score: float = 0.0
    mv_raw: float = 0.0
    tamper_rx: float | None = None
    attack_rx: float | None = None
    attack_why: str = ""
    rssi_alarm_rx: float | None = None
    offline_rx: float | None = None
    online: bool = True
    buffered_count: int = 0
    last_rssi: float | None = None
    fault: str | None = None
    fault_rx: float | None = None
    incidents: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        c = self.cfg
        se = c.sens_environment
        warm = c.learning_for(self.device)
        # couche 2 : niveau (CUSUM) + vitesse de montée (Holt) par capteur
        self.c_gas = _cusum("gas_ratio", se, "up", warmup_s=warm)
        self.c_temp = _cusum("temp_c", se, "both", warmup_s=warm)
        self.c_hum = _cusum("hum_pct", se, "both", warmup_s=warm)
        self.c_rssi = _cusum("rssi", c.sens_cyber, "down", warmup_s=warm, ref_size=120)
        self.h_gas = Holt(tau_level=10.0, tau_trend=CALIBRATION["gas_ratio"]["tau_trend"])
        self.h_temp = Holt(tau_level=20.0, tau_trend=CALIBRATION["temp_c"]["tau_trend"])
        self.r_gas = RateOfRise(self.h_gas, floor_per_min=CALIBRATION["gas_ratio"]["rate_floor"],
                                margin=c.rate_margin(se), scale=100.0)
        self.r_temp = RateOfRise(self.h_temp, floor_per_min=CALIBRATION["temp_c"]["rate_floor"],
                                 margin=c.rate_margin(se))
        self.pir = PoissonRate()
        # couche 3
        self.mv = MultivariateDetector(seed=self.seed)

    def apply(self, cfg: BrainConfig) -> None:
        """Nouveau profil de site : seuils et sensibilités changent sans perdre l'apprentissage."""
        self.cfg = cfg
        for det, name, sens in ((self.c_gas, "gas_ratio", cfg.sens_environment),
                                (self.c_temp, "temp_c", cfg.sens_environment),
                                (self.c_hum, "hum_pct", cfg.sens_environment),
                                (self.c_rssi, "rssi", cfg.sens_cyber)):
            det.h = CALIBRATION[name]["h"] * cfg.h_scale(sens)
        self.r_gas.margin = self.r_temp.margin = cfg.rate_margin(cfg.sens_environment)


class SentinelBrain:
    def __init__(self, cfg: BrainConfig | None = None, seed: int = 42, policy: SitePolicy | None = None):
        self.cfg = cfg or BrainConfig()
        self.policy = policy or SitePolicy()
        self.seed = seed
        self.quality = DataQuality()
        self.devices: dict[str, DeviceBrain] = {}
        self.cameras: dict[str, CameraBrain] = {}
        self.broker = BrokerWatch()
        self.pir_rx: float | None = None          # dernier mouvement PIR, tous boîtiers confondus

    @classmethod
    def from_profile(cls, profile: dict, device: str | None = None, seed: int = 42) -> SentinelBrain:
        return cls(BrainConfig.from_profile(profile, device), seed, SitePolicy.from_profile(profile))

    def update_profile(self, profile: dict, device: str | None = None) -> None:
        """Rechargement à chaud (message conservé sentinel/site/config)."""
        self.cfg = BrainConfig.from_profile(profile, device)
        self.policy = SitePolicy.from_profile(profile)
        for d in self.devices.values():
            d.apply(self.cfg)

    # ------------------------------------------------------------------ entrée unique
    def handle(self, topic: str, payload, rx_ts: float) -> list[dict]:
        parts = topic.split("/")
        if len(parts) != 3 or parts[0] != "sentinel" or parts[1] in ("site", "brain"):
            return []
        device, kind = parts[1], parts[2]
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8", "replace")
        if isinstance(payload, str) and kind != "status":
            try:
                payload = json.loads(payload)
            except ValueError:
                return []
        if kind == "vision" and isinstance(payload, dict):
            return self._vision(device, payload, rx_ts)
        if kind == "status" and (device in self.cameras or device.startswith("cam-")):
            return self._camera_status(device, str(payload), rx_ts)
        d = self.devices.get(device) or self.devices.setdefault(device, DeviceBrain(self.cfg, self.seed, device))
        if kind == "telemetry" and isinstance(payload, dict):
            return self._telemetry(device, d, payload, rx_ts)
        if kind == "event" and isinstance(payload, dict):
            return self._event(device, d, payload, rx_ts)
        if kind == "health" and isinstance(payload, dict):
            return self._health(device, d, payload, rx_ts)
        if kind == "status":
            d.online = str(payload) != "offline"
            if not d.online:
                d.offline_rx = rx_ts
            elif d.rssi_alarm_rx is None or rx_ts - d.rssi_alarm_rx > 180:
                d.offline_rx = None     # retour sans signe de brouillage (redémarrage, coupure courte) : on oublie
            return self._incidents(device, d, rx_ts, None)
        return []

    def tick(self, rx_ts: float) -> list[dict]:
        """À appeler régulièrement (2 s) : ce qui se juge sur l'absence de message."""
        out: list[dict] = []
        for cam_id, cam in self.cameras.items():
            if cam.online and rx_ts - cam.last_rx > self.policy.camera_timeout_s:
                cam.online, cam.offline_rx = False, cam.last_rx + self.policy.camera_timeout_s
            out += self._camera_incidents(cam_id, cam, rx_ts)
        out += self._broker_incidents(rx_ts)
        return out

    def security_event(self, reason: str, source: str | None, rx_ts: float) -> list[dict]:
        """Une tentative refusée par le broker (mot de passe, ACL, certificat)."""
        self.broker.failures.append((rx_ts, reason, source))
        return self._broker_incidents(rx_ts)

    # ------------------------------------------------------------------ boîtiers
    def _event(self, device: str, d: DeviceBrain, ev: dict, rx_ts: float) -> list[dict]:
        res = QualityResult()
        self.quality.check_sequence(ev, rx_ts, res)
        if res.replay_attack or res.stale:
            d.attack_rx, d.attack_why = rx_ts, "; ".join(res.issues)
        elif ev.get("type") == "tamper" and ev.get("value"):
            d.tamper_rx = rx_ts
        elif ev.get("type") == "pir" and ev.get("value"):
            self.pir_rx = rx_ts
        return self._incidents(device, d, rx_ts, None)

    def _health(self, device: str, d: DeviceBrain, h: dict, rx_ts: float) -> list[dict]:
        if isinstance(h.get("rssi"), (int, float)):
            d.last_rssi = float(h["rssi"])
            if d.c_rssi.update(d.last_rssi, float(h.get("ts", rx_ts))).alarm:
                d.rssi_alarm_rx = rx_ts
        return self._incidents(device, d, rx_ts, None)

    def _telemetry(self, device: str, d: DeviceBrain, m: dict, rx_ts: float) -> list[dict]:
        # ---- couche 1 : qualité et intégrité
        q = self.quality.check_telemetry(m, rx_ts)
        if q.replay_attack or q.stale:
            d.attack_rx, d.attack_why = rx_ts, "; ".join(q.issues)
        if q.sensor_fault:
            d.fault, d.fault_rx = q.sensor_fault, rx_ts
        if q.buffered:
            d.buffered_count += 1
        if not q.ok:                                   # rien d'autre ne voit ce message
            return self._incidents(device, d, rx_ts, None)

        c = self.cfg
        t = float(m["ts"])
        if d.first_ts is None:
            d.first_ts = t
        learning = m.get("mode") == "learning" or t - d.first_ts < c.learning_for(device)
        dt = 2.0 if d.last_t is None else max(0.0, t - d.last_t)
        d.last_t = t
        temp, hum, gas = float(m["temp_c"]), float(m["hum_pct"]), float(m["gas_ratio"])
        # DHT11 : pas de 1 °C, on lisse avant tout calcul de niveau ou de pente
        d.temp_s = temp if d.temp_s is None else d.temp_s + (1 - math.exp(-dt / 20.0)) * (temp - d.temp_s)
        pir_count = int(m.get("pir_count", 0))
        if m.get("pir") and not q.buffered:
            self.pir_rx = rx_ts

        # ---- couche 2 : niveau (CUSUM) et vitesse de montée, capteur par capteur
        og, ot, oh = d.c_gas.update(gas, t), d.c_temp.update(d.temp_s, t), d.c_hum.update(hum, t)
        d.h_gas.update(gas, t)
        d.h_temp.update(d.temp_s, t)
        quiet = og.score < 30 and ot.score < 30 and not d.incidents
        rg_score, rg_alarm = d.r_gas.update(t, healthy=quiet)
        rt_score, rt_alarm = d.r_temp.update(t, healthy=quiet)
        # PIR : test de Poisson ; plus sensible quand la caméra ne voit plus (masquée, sombre, hors ligne)
        boost = 0.75 if self._camera_view(rx_ts)["degraded"] else 1.0
        p60 = 10.0 ** (-4.0 * c.h_scale(c.sens_physical) * boost)     # sensibilité 0,6 -> 1e-4
        pir_score, pir_p = d.pir.update(pir_count, t, learn=pir_count <= 2, p60=p60)
        gas_alarm = og.alarm or rg_alarm or gas >= c.gas_warning
        temp_alarm = (ot.alarm and ot.direction == "up") or rt_alarm or temp >= c.temp_warning

        # ---- couche 4 : prévision (seulement quand une montée est en cours : pas d'eta sur du bruit)
        # la tendance de Holt réagit avec ~40 s de retard : si la mesure passe sous le niveau lissé, ça redescend
        eta_gas = d.h_gas.eta_min(c.gas_critical, 0.01, c.horizon_min) \
            if gas_alarm and gas >= d.h_gas.level else None
        eta_temp = d.h_temp.eta_min(c.temp_critical, 0.1, c.horizon_min) \
            if temp_alarm and d.temp_s >= d.h_temp.level else None
        etas = [e for e in (eta_gas, eta_temp) if e is not None]
        eta = min(etas) if etas else None

        # ---- couche 3 : multivariée, une fenêtre de 60 s toutes les 10 s
        d.window.append((t, d.temp_s, hum, gas, pir_count))
        while d.window and d.window[0][0] < t - c.window_s:
            d.window.popleft()
        sensors = max(og.score, ot.score, 0.5 * oh.score, rg_score, rt_score)
        if t - d.last_feat_t >= 10.0:
            d.last_feat_t = t
            f = window_features(d.window)
            if f is not None:
                d.mv_score, d.mv_raw = d.mv.score(f)
                if sensors < 50 and pir_score < 60 and not d.incidents:   # on n'apprend que du sain
                    d.mv.learn(f)

        # ---- fusion : domaine environnement
        raw_guard = 0.0
        if gas >= c.gas_critical or temp >= c.temp_critical:
            raw_guard = 100.0
        elif gas >= c.gas_warning or temp >= c.temp_warning:
            raw_guard = 60.0
        fc = 0.0 if eta is None else 60.0 + 40.0 * (1.0 - eta / c.horizon_min)
        env = max(sensors, d.mv_score, raw_guard, fc)
        eta_by = {k: v for k, v in (("gas_ratio", eta_gas), ("temp_c", eta_temp)) if v is not None}
        ctx = {"eta_by": eta_by, "t": t, "gas": gas, "temp": temp, "hum": hum, "og": og, "ot": ot, "oh": oh,
               "rg": (rg_score, rg_alarm), "rt": (rt_score, rt_alarm), "gas_alarm": gas_alarm,
               "temp_alarm": temp_alarm, "eta": eta, "env": env, "pir_score": pir_score, "pir_p": pir_p,
               "pir_count": pir_count, "learning": learning, "buffered": q.buffered, "raw_guard": raw_guard,
               "fc": fc}
        out = [] if learning else self._incidents(device, d, rx_ts, ctx)
        if not q.buffered:
            out.append(self._score(device, d, ctx, rx_ts))
        return out

    # ------------------------------------------------------------------ vision
    def _camera_view(self, rx_ts: float) -> dict:
        """Ce que voient les caméras en ce moment (la plus récente fait foi)."""
        live = [c for c in self.cameras.values() if c.online and rx_ts - c.last_rx <= self.policy.camera_timeout_s]
        if not self.cameras:
            return {"exists": False, "degraded": False, "persons": [], "phys": 0.0}
        persons = [p for c in live for p in c.persons if p.in_zone]
        degraded = not live or any(c.masked or c.low_light for c in live)
        return {"exists": True, "degraded": degraded, "persons": persons,
                "phys": max((c.phys_score for c in live), default=0.0)}

    def _camera_status(self, cam_id: str, status: str, rx_ts: float) -> list[dict]:
        cam = self.cameras.setdefault(cam_id, CameraBrain(first_rx=rx_ts, last_rx=rx_ts))
        if status == "offline" and cam.online:
            cam.online, cam.offline_rx = False, rx_ts
        elif status == "online":
            cam.online = True
        return self._camera_incidents(cam_id, cam, rx_ts)

    def _vision(self, cam_id: str, m: dict, rx_ts: float) -> list[dict]:
        cam = self.cameras.setdefault(cam_id, CameraBrain(first_rx=rx_ts, last_rx=rx_ts))
        res = QualityResult()
        self.quality.check_sequence(m, rx_ts, res)
        if res.replay_attack or res.stale:                 # même contrôle anti-rejeu que les boîtiers
            cam.attack_rx, cam.attack_why = rx_ts, "; ".join(res.issues)
            return self._camera_incidents(cam_id, cam, rx_ts)
        t = float(m.get("ts", rx_ts))
        cam.last_rx, cam.last_ts, cam.online = rx_ts, t, True
        cam.fps, cam.brightness = m.get("fps"), m.get("brightness")
        masked = bool(m.get("masked"))
        if masked and not cam.masked:
            cam.masked_since = rx_ts
        cam.masked, cam.low_light = masked, bool(m.get("low_light"))
        cam.persons = []
        for p in m.get("persons", []) or []:
            ok, badge, off = self.policy.check_badge(p.get("badge"), t)
            cam.persons.append(Person(int(p.get("track_id", -1)), bool(p.get("in_zone")), float(p.get("dwell_s", 0)),
                                      p.get("badge"), ok, off, badge.name if badge else None))
        if any(p.in_zone for p in cam.persons):
            cam.last_person_rx = rx_ts
        out = self._camera_incidents(cam_id, cam, rx_ts)
        out.append(self._camera_score(cam_id, cam, t))
        return out

    def _camera_conditions(self, cam: CameraBrain, rx_ts: float) -> dict[str, tuple[str, str, list]]:
        pol, out = self.policy, {}
        zone = [p for p in cam.persons if p.in_zone] if cam.online else []
        intruders = [p for p in zone if not p.authorized and not p.off_hours]   # badge connu hors horaires : à vérifier
        agents = [p for p in zone if p.authorized]
        late = [p for p in zone if p.off_hours]
        pir_gap = None if self.pir_rx is None else abs(rx_ts - self.pir_rx)
        names = ", ".join(sorted({p.name for p in agents if p.name})) or "un agent"
        if intruders:
            n = len(intruders)
            who = f"{n} personne{'s' if n > 1 else ''} sans badge autorisé"
            fac = [("persons_unauthorized", n, 70.0)]
            if agents:
                out["intrusion_suspected"] = ("warning", f"{who} dans la zone, accompagnée{'s' if n > 1 else ''} "
                                              f"de {names} (accompagnement à vérifier)", fac)
            elif pir_gap is not None and pir_gap <= pol.correlation_window_s:
                out["intrusion_confirmed"] = ("critical", f"{who} dans la zone, confirmée par le PIR "
                                              f"({_fmt(pir_gap)} s d'écart)", fac + [("pir_gap_s", pir_gap, 30.0)])
            else:
                longest = max(p.dwell_s for p in intruders)
                if 0 < pol.vision_confirm_s <= longest:   # la vision suffit : personne inconnue restée N s
                    out["intrusion_confirmed"] = ("critical", f"{who} dans la zone depuis {longest:.0f} s, "
                                                  "confirmée par la vision (PIR silencieux)",
                                                  fac + [("dwell_s", round(longest, 1), 30.0)])
                else:
                    out["intrusion_suspected"] = ("warning", f"{who} dans la zone (vision seule, PIR silencieux)",
                                                  fac)
            longest = max(p.dwell_s for p in intruders)
            if longest >= pol.loitering_s:
                out["loitering"] = ("warning", f"Présence prolongée dans la zone : {longest:.0f} s "
                                    f"(seuil {pol.loitering_s:.0f} s)", [("dwell_s", round(longest, 1), 75.0)])
        elif late:
            p = late[0]
            b = pol.badges.get(int(p.badge)) if p.badge is not None else None
            out["presence_to_verify"] = ("warning", f"Badge valide de {p.name} mais hors de ses horaires "
                                         f"({b.hours_txt if b else '?'})", [("badge", p.badge, 50.0)])
        elif agents:
            out["presence_authorized"] = ("info", f"{names} dans la zone, badge reconnu, horaires respectés",
                                          [("badge", agents[0].badge, 10.0)])
        if cam.online and cam.masked:
            since = rx_ts - (cam.masked_since or rx_ts)
            out["sabotage"] = ("critical", f"Caméra masquée : image uniforme depuis {since:.0f} s",
                               [("masked", True, 100.0)])
        elif cam.online and cam.low_light:
            out["camera_degraded"] = ("info", f"Image trop sombre (luminosité {cam.brightness or 0:.0f}/255) : "
                                      "le PIR prend le relais", [("brightness", cam.brightness, 20.0)])
        if not cam.online:
            silent = rx_ts - (cam.offline_rx or rx_ts)
            recent = [x for x in (cam.last_person_rx, self.pir_rx)
                      if x is not None and 0 <= (cam.offline_rx or rx_ts) - x <= pol.sabotage_window_s]
            if recent:
                out["sabotage"] = ("critical", "Caméra muette juste après une détection "
                                   f"(hors ligne depuis {silent:.0f} s)", [("camera_offline", True, 100.0)])
            else:
                out["camera_degraded"] = ("warning", f"Caméra hors ligne depuis {silent:.0f} s",
                                          [("camera_offline", True, 60.0)])
        if cam.attack_rx is not None and rx_ts - cam.attack_rx <= self.cfg.cooldown_s:
            out["cyber_attack"] = ("critical", f"Message vision rejeté par le contrôle d'intégrité : {cam.attack_why}",
                                   [("integrity", cam.attack_why, 100.0)])
        return out

    def _camera_incidents(self, cam_id: str, cam: CameraBrain, rx_ts: float) -> list[dict]:
        conds = self._camera_conditions(cam, rx_ts)
        cam.phys_score = max([CAMERA_SCORE.get(k, 0.0) for k in conds] + [0.0])
        cyber = 100.0 if "cyber_attack" in conds else 0.0
        return self._emit(cam_id, cam, conds, rx_ts, cam.last_ts or rx_ts, None, (0.0, cam.phys_score, cyber))

    def _camera_score(self, cam_id: str, cam: CameraBrain, t: float) -> dict:
        n_in = sum(p.in_zone for p in cam.persons)
        return {"kind": "score", "topic": "sentinel/brain/score", "payload": {
            "device_id": cam_id, "ts": int(t), "score": round(cam.phys_score), "environment": 0,
            "physical": round(cam.phys_score), "cyber": 0, "eta_min": None, "eta_by": {}, "learning": False,
            "layers": {"persons_in_zone": n_in, "unauthorized": sum(p.in_zone and not p.authorized for p in cam.persons),
                       "masked": int(cam.masked), "low_light": int(cam.low_light)}}}

    # ------------------------------------------------------------------ broker (journal de Mosquitto)
    def _broker_incidents(self, rx_ts: float) -> list[dict]:
        pol, out = self.policy, {}
        burst = self.broker.burst(rx_ts, pol.auth_failure_window_s)
        if len(burst) >= pol.auth_failure_burst:
            sources = sorted({s for _, _, s in burst if s})
            reasons = sorted({r for _, r, _ in burst})
            out["cyber_attack"] = ("critical", f"Rafale de {len(burst)} accès MQTT refusés en "
                                   f"{pol.auth_failure_window_s:.0f} s ({', '.join(reasons)})"
                                   + (f" depuis {', '.join(sources)}" if sources else ""),
                                   [("refused", len(burst), 100.0)])
        return self._emit("broker", self.broker, out, rx_ts, rx_ts, None,
                          (0.0, 0.0, 100.0 if out else 0.0))

    # ------------------------------------------------------------------ scores des boîtiers
    def _domain_scores(self, d: DeviceBrain, ctx: dict | None, rx_ts: float) -> tuple[float, float, float]:
        env = ctx["env"] if ctx else 0.0
        tamper = _decay(None if d.tamper_rx is None else rx_ts - d.tamper_rx, 30, 120)
        view = self._camera_view(rx_ts)
        phys = max(ctx["pir_score"] if ctx else 0.0, tamper, view["phys"])
        cyber = max(_decay(None if d.attack_rx is None else rx_ts - d.attack_rx, 60, 240),
                    0.0 if d.rssi_alarm_rx is None else 0.6 * _decay(rx_ts - d.rssi_alarm_rx, 30, 120),
                    0.0 if d.offline_rx is None else 0.8 * _decay(rx_ts - d.offline_rx, 300, 300),
                    100.0 if self.broker.incidents else 0.0)
        return env, phys, cyber

    def _score(self, device: str, d: DeviceBrain, ctx: dict, rx_ts: float) -> dict:
        env, phys, cyber = self._domain_scores(d, ctx, rx_ts)
        m = max(env, phys, cyber)
        total = min(100.0, m + 0.15 * (env + phys + cyber - m))       # maximum pondéré
        return {"kind": "score", "topic": "sentinel/brain/score", "payload": {
            "device_id": device, "ts": int(ctx["t"]), "score": round(total), "environment": round(env),
            "physical": round(phys), "cyber": round(cyber), "eta_min": ctx["eta"], "eta_by": ctx["eta_by"],
            "learning": ctx["learning"],
            "layers": {"cusum_gas": round(ctx["og"].score), "rate_gas": round(ctx["rg"][0]),
                       "cusum_temp": round(ctx["ot"].score), "rate_temp": round(ctx["rt"][0]),
                       "cusum_hum": round(ctx["oh"].score), "iforest": round(d.mv_score),
                       "forecast": round(ctx["fc"]), "raw": round(ctx["raw_guard"])}}}

    # ------------------------------------------------------------------ règles des boîtiers
    def _conditions(self, d: DeviceBrain, ctx: dict | None, rx_ts: float) -> dict[str, tuple[str, str, list]]:
        """{type: (gravité, explication, facteurs)} pour chaque incident dont la condition est vraie."""
        c, out = self.cfg, {}
        if ctx is not None:
            og, ot, oh = ctx["og"], ctx["ot"], ctx["oh"]
            eta = ctx["eta"]
            gas_pct = 100.0 * (ctx["gas"] / og.baseline - 1.0)
            temp_rate = d.r_temp.rate
            hum_down = oh.alarm and oh.direction == "down"
            crit = ctx["gas"] >= c.gas_critical or ctx["temp"] >= c.temp_critical or (eta is not None and eta <= 3)
            sev = "critical" if crit else "warning"
            eta_txt = ""
            if eta is not None:
                what = (f"ratio gaz critique ({_fmt(c.gas_critical)})" if ctx["eta_by"].get("gas_ratio") == eta
                        else f"{_fmt(c.temp_critical, 0)} °C")
                eta_txt = f" ; {what} prévu dans {_fmt(eta)} min"
            factors = [("gas_ratio", ctx["gas"], max(og.score, ctx["rg"][0])),
                       ("temp_c", ctx["temp"], max(ot.score, ctx["rt"][0])),
                       ("hum_pct", ctx["hum"], 0.5 * oh.score), ("iforest", round(d.mv_raw), d.mv_score),
                       ("eta_min", eta, ctx["fc"])]
            temp_rising = ctx["temp_alarm"] or (ot.direction == "up" and ot.s_up >= d.c_temp.h / 2)
            if ctx["gas_alarm"] and temp_rising:
                out["fire_risk"] = ("critical", f"Gaz {gas_pct:+.0f} % et température en hausse "
                                    f"({_fmt(ctx['temp'], 0)} °C, {_fmt(temp_rate)} °C/min)"
                                    + (", humidité en baisse" if hum_down else "") + eta_txt, factors)
            elif ctx["gas_alarm"]:
                out["gas_leak"] = (sev, f"Gaz {gas_pct:+.0f} % au-dessus de la ligne de base "
                                   f"(ratio {_fmt(ctx['gas'], 2)}), montée de {d.r_gas.rate:+.0f} %/min "
                                   f"(maximum sain {_fmt(d.r_gas.threshold, 0)} %/min), température stable "
                                   f"({_fmt(ctx['temp'], 0)} °C)" + eta_txt, factors)
            elif ctx["temp_alarm"]:
                out["thermal_drift"] = (sev, f"Température en dérive : {_fmt(ot.value)} °C (lissée) contre "
                                        f"{_fmt(ot.baseline)} °C habituels, {_fmt(temp_rate)} °C/min, gaz stable"
                                        + (", humidité en baisse" if hum_down else "") + eta_txt, factors)
            elif d.mv_score >= 60:
                out["unusual_pattern"] = ("info", "Combinaison de mesures inhabituelle (Isolation Forest) alors "
                                          "qu'aucun capteur ne dépasse seul sa ligne de base", factors)
            # PIR seul : la caméra, si elle voit, a le dernier mot (agent badgé = pas d'intrusion ;
            # personne dans la zone = incident déjà porté par la caméra)
            view = self._camera_view(rx_ts)
            camera_covers = view["exists"] and not view["degraded"] and view["persons"]
            if ctx["pir_score"] >= 60 and not camera_covers:
                blind = " ; caméra aveugle, le PIR fait foi" if view["degraded"] and view["exists"] else ""
                out["intrusion_suspected"] = (
                    "warning", f"{ctx['pir_count']} détections PIR en une minute contre "
                    f"{_fmt(d.pir.rate)} habituellement (probabilité {ctx['pir_p']:.0e} que ce soit le hasard)"
                    + blind, [("pir_count", ctx["pir_count"], ctx["pir_score"])])
        if d.tamper_rx is not None and rx_ts - d.tamper_rx <= c.cooldown_s:
            out["sabotage"] = ("critical", "Ouverture ou manipulation du boîtier (capteur tactile du couvercle)",
                               [("tamper", True, 100.0)])
        if d.attack_rx is not None and rx_ts - d.attack_rx <= c.cooldown_s:
            out["cyber_attack"] = ("critical", f"Message rejeté par le contrôle d'intégrité : {d.attack_why}",
                                   [("integrity", d.attack_why, 100.0)])
        if d.rssi_alarm_rx is not None and (rx_ts - d.rssi_alarm_rx <= 180 or not d.online):
            offline = d.offline_rx is not None and 0 <= d.offline_rx - d.rssi_alarm_rx <= 180
            out["jamming_suspected"] = (
                "critical" if offline else "warning",
                f"Signal Wi-Fi en chute (RSSI {_fmt(d.last_rssi or 0, 0)} dBm contre "
                f"{_fmt(d.c_rssi.mu or 0, 0)} habituels)" + (", puis boîtier hors ligne" if offline else ""),
                [("rssi", d.last_rssi, 60.0), ("offline", offline, 100.0 if offline else 0.0)])
        if d.fault_rx is not None and rx_ts - d.fault_rx <= c.cooldown_s:
            out["sensor_fault"] = ("warning", f"Capteur défaillant : {d.fault}", [("fault", d.fault, 60.0)])
        return out

    def _incidents(self, device: str, d: DeviceBrain, rx_ts: float, ctx: dict | None) -> list[dict]:
        conds = self._conditions(d, ctx, rx_ts)
        return self._emit(device, d, conds, rx_ts, ctx["t"] if ctx else rx_ts, ctx,
                          self._domain_scores(d, ctx, rx_ts))

    # ------------------------------------------------------------------ cycle de vie des incidents
    def _emit(self, device: str, holder, conds: dict, rx_ts: float, t: float, ctx: dict | None,
              scores: tuple[float, float, float]) -> list[dict]:
        """Ouvre, fait monter en gravité ou clôt les incidents d'un boîtier, d'une caméra ou du broker."""
        alerts = []
        for ranks in (ENV_RANK, PERSON_RANK):
            for new in [k for k in conds if k in ranks]:
                olds = [o for o in holder.incidents if o in ranks and o != new]
                if olds and ranks[new] <= max(ranks[o] for o in olds):
                    old = max(olds, key=ranks.get)        # l'incident déjà ouvert continue, sans nouvelle alerte
                    conds.setdefault(old, conds[new])
                    del conds[new]
        for typ, (sev, why, factors) in conds.items():
            inc = holder.incidents.get(typ)
            if inc is None:
                inc = holder.incidents[typ] = Incident(typ, sev, t, rx_ts)
            inc.last_true_rx, inc.severity, inc.false_since = rx_ts, sev, None
            # une alerte à l'ouverture, puis seulement si la gravité monte (l'API regroupe, pas de spam)
            if inc.emitted_severity is None or SEVERITY_RANK[sev] > SEVERITY_RANK[inc.emitted_severity]:
                inc.emitted_severity = sev
                alerts.append(self._alert(device, holder, inc, why, factors, ctx, rx_ts, t, scores))
        # clôture quand la condition est OBSERVÉE fausse pendant cooldown_s (hystérésis). Les incidents
        # environnement ne se jugent que sur une mesure : une coupure réseau ne doit pas clore une fuite de gaz.
        for typ in list(holder.incidents):
            if typ in conds or (DOMAIN_OF[typ] == "environment" and ctx is None):
                continue
            inc = holder.incidents[typ]
            if inc.false_since is None:
                inc.false_since = rx_ts
            elif rx_ts - inc.false_since > self.cfg.cooldown_s:
                del holder.incidents[typ]
        return alerts

    def _alert(self, device: str, holder, inc: Incident, why: str, factors: list, ctx: dict | None,
               rx_ts: float, t: float, scores: tuple[float, float, float]) -> dict:
        tot = sum(max(0.0, float(f[2] or 0.0)) for f in factors) or 1.0
        fl = [{"name": n, "value": v, "contribution": round(max(0.0, float(s)) / tot, 2)} for n, v, s in factors if s]
        fl.sort(key=lambda f: -f["contribution"])
        env, phys, cyber = scores
        domain = DOMAIN_OF[inc.type]
        score = {"environment": env, "physical": phys, "cyber": cyber}.get(domain, 60.0)
        score = max(score, CAMERA_SCORE.get(inc.type, 0.0))
        if inc.severity != "info":
            score = max(score, 60.0)
        return {"kind": "alert", "payload": {
            "device_id": device, "source": "brain", "domain": domain, "type": inc.type, "severity": inc.severity,
            "score": round(min(100.0, score)), "eta_min": ctx["eta"] if ctx else None, "ts": int(t),
            "explanation": why, "factors": fl[:4],
            "details": {"retrospective": bool(ctx and ctx["buffered"]), "rx_ts": rx_ts,
                        "buffered_received": holder.buffered_count}}}
