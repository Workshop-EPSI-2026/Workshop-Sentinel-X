"""Modèles du contrat d'interface (docs/contracts.md) : validation stricte de tout ce qui entre."""
from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

DeviceId = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{0,31}$")]
Ts = Annotated[float, Field(gt=1_600_000_000, lt=4_000_000_000)]  # secondes Unix plausibles
Score = Annotated[float, Field(ge=0, le=100)]
Mode = Literal["learning", "armed", "maintenance"]
Severity = Literal["info", "warning", "critical"]
Domain = Literal["environment", "physical", "cyber", "maintenance"]
AlertStatus = Literal["open", "acknowledged", "resolved"]
AlertType = Literal[
    "intrusion_confirmed", "intrusion_suspected", "loitering", "sabotage", "fire_risk", "gas_leak",
    "jamming_suspected", "cyber_attack", "sensor_fault",
]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Lenient(BaseModel):
    # Messages des boîtiers : un champ en plus (nouveau firmware) ne doit pas faire perdre la mesure
    model_config = ConfigDict(extra="ignore")


# ------------------------------------------------------------------------------------------------ MQTT (boîtiers, Brain)
class Telemetry(Lenient):
    device_id: DeviceId
    seq: int = Field(ge=0)
    boot_id: str = Field(min_length=1, max_length=64)
    ts: Ts
    temp_c: float = Field(ge=-20, le=80)
    hum_pct: float = Field(ge=0, le=100)
    gas_mv: int = Field(ge=0, le=5000)
    gas_ratio: float = Field(ge=0, le=20)
    gas_do: bool
    pir: bool
    pir_count: int = Field(ge=0, le=1000)
    mode: Mode
    edge_score: int = Field(ge=0, le=100)
    replay: bool = False


class DeviceEvent(Lenient):
    device_id: DeviceId
    seq: int = Field(ge=0)
    boot_id: str = Field(min_length=1, max_length=64)
    ts: Ts
    type: Literal["pir", "tamper", "gas_do", "edge_alarm", "boot", "mode_change"]
    value: Any = None
    details: dict[str, Any] = Field(default_factory=dict)


class DeviceHealth(Lenient):
    device_id: DeviceId
    ts: Ts
    uptime_s: int = Field(ge=0)
    heap_free: int = Field(ge=0)
    psram_free: int = Field(ge=0)
    rssi: int = Field(ge=-127, le=0)
    chip_temp_c: float
    reset_reason: str = Field(max_length=40)
    buffer_len: int = Field(ge=0)
    wifi_disconnects: int = Field(ge=0)
    mqtt_reconnects: int = Field(ge=0)
    tls_errors: int = Field(ge=0)
    fw_version: str = Field(max_length=40)


class DeviceStatus(BaseModel):
    device_id: str
    status: Literal["online", "offline"]
    ts: float


class Scores(Lenient):
    ts: Ts
    global_: Score = Field(alias="global")
    environment: Score
    physical: Score
    cyber: Score

    def out(self) -> dict[str, float]:
        return self.model_dump(by_alias=True)


# ------------------------------------------------------------------------------------------------------- REST : entrée
class Factor(Strict):
    name: str = Field(max_length=60)
    value: float
    contribution: float = Field(ge=0, le=1)


class AlertIn(Strict):
    """POST /api/v1/alerts (vision, Brain) : alerte brute, regroupée en incident par l'API."""
    device_id: DeviceId
    source: Literal["vision", "brain", "edge"]
    domain: Domain
    type: AlertType
    severity: Severity
    score: Score
    eta_min: float | None = Field(default=None, ge=0, le=1440)
    ts: Ts
    explanation: str = Field(min_length=1, max_length=500)
    factors: list[Factor] = Field(default_factory=list, max_length=10)
    details: dict[str, Any] = Field(default_factory=dict)


class AlertPatch(Strict):
    status: Literal["acknowledged", "resolved"]


class CommandIn(Strict):
    device_id: DeviceId
    cmd: Literal["alarm", "led", "mode", "recalibrate", "reboot"]
    on: bool | None = None
    color: Literal["green", "blue", "orange", "red", "violet", "white", "off"] | None = None
    value: Mode | None = None

    def payload(self) -> dict[str, Any]:
        """Champs propres à la commande, vérifiés selon son type."""
        required = {"alarm": "on", "led": "color", "mode": "value"}.get(self.cmd)
        if required and getattr(self, required) is None:
            raise ValueError(f"la commande {self.cmd} exige le champ {required}")
        body: dict[str, Any] = {"cmd": self.cmd}
        if required:
            body[required] = getattr(self, required)
        return body


class ConfigIn(Strict):
    profile: SiteProfile


# Profil de site : structure de config/site.example.yml, bornes de sécurité sur les valeurs réglables
class DeviceProfile(Strict):
    label: str = Field(max_length=80)
    sensors: dict[Literal["dht11", "mq2", "pir", "tamper"], bool]
    telemetry_period_s: int = Field(ge=1, le=60)
    burst_period_ms: int = Field(ge=200, le=5000)
    burst_duration_s: int = Field(ge=10, le=600)
    local_alarm: bool
    buzzer: bool
    tamper_sensitivity: float = Field(ge=0, le=1)
    learning_minutes: int = Field(ge=1, le=120)


class Threshold(Strict):
    warning: float
    critical: float


class Schedule(Strict):
    days: list[Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]]
    from_: str = Field(alias="from", pattern=r"^\d{2}:\d{2}$")
    to: str = Field(pattern=r"^\d{2}:\d{2}$")
    profile: str = Field(max_length=20)


class Modes(Strict):
    default: Literal["armed", "maintenance"]
    schedule: list[Schedule] = Field(default_factory=list)


class Brain(Strict):
    sensitivity: dict[Literal["environment", "physical", "cyber"], float]
    night_profile_boost: float = Field(ge=0, le=0.5)
    window_s: int = Field(ge=10, le=600)
    retrain_every_min: int = Field(ge=1, le=1440)
    forecast_horizon_min: int = Field(ge=1, le=120)
    correlation_window_s: int = Field(ge=1, le=60)
    loitering_s: int = Field(ge=1, le=600)
    cooldown_s: int = Field(ge=0, le=3600)


class Vision(Strict):
    enabled: bool
    imgsz: Literal[320, 416, 480, 640]
    confidence: float = Field(ge=0.1, le=0.95)
    min_consecutive_frames: int = Field(ge=1, le=30)
    zone: list[tuple[float, float]] = Field(min_length=3, max_length=20)
    masking_detection: bool
    low_light_threshold: int = Field(ge=0, le=255)


class Site(Strict):
    name: str = Field(max_length=80)
    timezone: str = Field(max_length=40)


class Integrations(Strict):
    webhook_url: str = Field(default="", max_length=300)
    csv_export: bool = True


class SiteProfile(Strict):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    site: Site
    devices: dict[DeviceId, DeviceProfile]
    modes: Modes
    thresholds: dict[Literal["temp_c", "hum_pct", "gas_ratio"], Threshold]
    brain: Brain
    vision: Vision
    integrations: Integrations

    def checked(self) -> SiteProfile:
        for key, th in self.thresholds.items():
            if th.warning >= th.critical:
                raise ValueError(f"seuil {key} : l'avertissement doit être inférieur au seuil critique")
        for key, value in self.brain.sensitivity.items():
            if not 0 <= value <= 1:
                raise ValueError(f"sensibilité {key} : entre 0 et 1")
        return self

    def out(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True)


ConfigIn.model_rebuild()
