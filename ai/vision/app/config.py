"""Réglages du service vision : variables d'environnement + section vision du profil de site."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

VISION_DIR = Path(__file__).resolve().parents[1]
DEFAULT_ZONE = ((0.20, 0.25), (0.80, 0.25), (0.80, 0.95), (0.20, 0.95))


def _env(name: str, default: str) -> str:
    v = os.environ.get(name)
    return v if v not in (None, "") else default


def _bool(v: str) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "oui")


@dataclass
class VisionSettings:
    # source et modèle
    source: str = "0"                    # index de webcam, chemin d'une vidéo ou URL RTSP
    loop: bool = True                    # vidéo de démo : reprendre au début
    model: str = "yolov8n.pt"            # .pt (PC) ou dossier *_ncnn_model (Raspberry Pi)
    imgsz: int = 320
    confidence: float = 0.5
    device_id: str = "cam-01"
    # règles (profil de site)
    zone: tuple[tuple[float, float], ...] = DEFAULT_ZONE
    masking_detection: bool = True
    low_light_threshold: float = 35.0
    authorized_badges: dict[int, str] = field(default_factory=dict)   # affichage seulement : Brain décide
    aruco_dictionary: str = "DICT_4X4_50"
    # rythme
    publish_period_s: float = 1.0
    yolo_every_n_frames: int = 10        # sans mouvement : YOLO une image sur 10 (personne immobile)
    # réseau
    http_host: str = "127.0.0.1"         # PC : nginx (Docker Desktop) passe par host.docker.internal
    http_port: int = 8001
    mqtt_host: str = "localhost"
    mqtt_port: int = 8883
    mqtt_tls: bool = True
    mqtt_ca: str | None = None
    mqtt_user: str = "vision"
    mqtt_password: str | None = None
    mqtt_enabled: bool = True

    @property
    def model_path(self) -> str:
        p = Path(self.model)
        return str(p if p.is_absolute() else VISION_DIR / "models" / p)

    @classmethod
    def load(cls, profile_path: str | None = None, **overrides) -> VisionSettings:
        s = cls()
        root = VISION_DIR.parents[1]
        path = profile_path or _env("SITE_PROFILE", str(root / "config" / "site.example.yml"))
        if Path(path).exists():
            s.apply_profile(yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {})
        s.source = _env("VISION_SOURCE", s.source)
        s.model = _env("VISION_MODEL", s.model)
        s.device_id = _env("VISION_DEVICE_ID", s.device_id)
        s.http_host = _env("VISION_HTTP_HOST", s.http_host)
        s.http_port = int(_env("VISION_HTTP_PORT", str(s.http_port)))
        s.mqtt_host = _env("MQTT_HOST", s.mqtt_host)
        s.mqtt_port = int(_env("MQTT_PORT", str(s.mqtt_port)))
        s.mqtt_tls = _bool(_env("MQTT_TLS", str(s.mqtt_tls)))
        ca = _env("MQTT_CA", str(root / "security" / "certs" / "ca.crt"))
        s.mqtt_ca = ca if Path(ca).exists() else None
        s.mqtt_user = _env("MQTT_USER", s.mqtt_user)
        s.mqtt_password = os.environ.get("MQTT_PASSWORD") or os.environ.get("MQTT_VISION_PASSWORD")
        for k, v in overrides.items():
            if v is not None:
                setattr(s, k, v)
        return s

    def apply_profile(self, profile: dict) -> None:
        v = profile.get("vision", {}) or {}
        self.imgsz = int(v.get("imgsz", self.imgsz))
        self.confidence = float(v.get("confidence", self.confidence))
        if v.get("zone"):
            self.zone = tuple((float(x), float(y)) for x, y in v["zone"])
        self.masking_detection = bool(v.get("masking_detection", self.masking_detection))
        self.low_light_threshold = float(v.get("low_light_threshold", self.low_light_threshold))
        self.aruco_dictionary = str(v.get("aruco_dictionary", self.aruco_dictionary))
        self.authorized_badges = {int(b["id"]): str(b.get("name", b["id"]))
                                  for b in v.get("authorized_badges", []) or []}
