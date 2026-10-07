"""Configuration lue dans l'environnement (fourni par infra/docker-compose.yml et infra/.env)."""
from __future__ import annotations

import os
from dataclasses import dataclass


def _bool(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    database_url: str
    mqtt_host: str
    mqtt_port: int
    mqtt_tls: bool
    mqtt_ca: str
    mqtt_user: str
    mqtt_password: str
    api_key: str
    operator_token: str
    site_profile: str
    webhook_url: str
    vision_health_url: str
    db_pool_size: int

    @classmethod
    def from_env(cls) -> Settings:
        s = cls(
            database_url=os.environ["DATABASE_URL"],
            mqtt_host=os.environ.get("MQTT_HOST", "mosquitto"),
            mqtt_port=int(os.environ.get("MQTT_PORT", "8884")),
            mqtt_tls=_bool("MQTT_TLS", True),
            mqtt_ca=os.environ.get("MQTT_CA", "/certs/ca.crt"),
            mqtt_user=os.environ.get("MQTT_USER", "api"),
            mqtt_password=os.environ.get("MQTT_PASSWORD", ""),
            api_key=os.environ.get("API_KEY", ""),
            operator_token=os.environ.get("OPERATOR_TOKEN", ""),
            site_profile=os.environ.get("SITE_PROFILE", "/config/site.yml"),
            webhook_url=os.environ.get("WEBHOOK_URL", ""),
            vision_health_url=os.environ.get("VISION_HEALTH_URL", ""),
            db_pool_size=int(os.environ.get("DB_POOL_SIZE", "5")),
        )
        # Un jeton trop court se devine : l'API refuse de démarrer plutôt que d'exposer le système
        for name, value in (("API_KEY", s.api_key), ("OPERATOR_TOKEN", s.operator_token)):
            if len(value) < 32 or "CHANGE_ME" in value:
                raise RuntimeError(f"{name} doit faire au moins 32 caractères et ne pas valoir CHANGE_ME (infra/.env)")
        return s
