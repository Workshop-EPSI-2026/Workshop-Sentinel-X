"""Logique métier : ingestion des messages MQTT, incidents, profil de site, commandes, santé, purge."""
from __future__ import annotations

import asyncio
import json
import logging
import time
import urllib.request
import uuid
from typing import Any

import psutil
import yaml
from pydantic import ValidationError

from .hub import Hub
from .models import AlertIn, CommandIn, DeviceEvent, DeviceHealth, DeviceStatus, Scores, SiteProfile, Telemetry
from .mqtt import MqttBridge
from .repo import Repo
from .settings import Settings

log = logging.getLogger("sentinel.service")

# Rétention : la base reste petite sur le PC serveur (la télémétrie arrive toutes les 2 s)
RETENTION_DAYS = {"telemetry": 30, "events": 90, "device_health": 7, "scores": 7, "audit_log": 180}


class ServiceError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


class Service:
    def __init__(self, settings: Settings, repo: Repo, hub: Hub) -> None:
        self.settings = settings
        self.repo = repo
        self.hub = hub
        self.mqtt: MqttBridge | None = None
        self.last_score_ts = 0.0
        self.rejected = 0

    # ------------------------------------------------------------------------------------------- démarrage
    async def seed_config(self) -> None:
        """Première version du profil de site, lue dans le fichier fourni par la stack (config/site.example.yml)."""
        current = await self.repo.latest_config()
        if current is None:
            with open(self.settings.site_profile, encoding="utf-8") as f:
                profile = SiteProfile.model_validate(yaml.safe_load(f)).checked()
            current = await self.repo.insert_config(profile.out(), "system")
            log.info("Profil de site initial enregistré (version %s)", current["version"])
        await self.repo.sync_device_labels(current["profile"]["devices"])

    async def on_mqtt_connected(self) -> None:
        """À chaque (re)connexion : profil republié en message conservé, pour les boîtiers et pour Brain."""
        current = await self.repo.latest_config()
        if current:
            self.publish_config(current["profile"])

    def publish_config(self, profile: dict[str, Any]) -> bool:
        if not self.mqtt:
            return False
        ok = self.mqtt.publish("sentinel/site/config", profile, retain=True)
        for device_id, device in profile["devices"].items():
            ok = self.mqtt.publish(f"sentinel/{device_id}/config", device, retain=True) and ok
        return ok

    # --------------------------------------------------------------------------------------------- ingestion
    async def handle_message(self, topic: str, payload: bytes) -> None:
        parts = topic.split("/")
        if len(parts) != 3 or parts[0] != "sentinel":
            return
        _, who, kind = parts
        try:
            if who == "brain" and kind == "score":
                await self._score(Scores.model_validate_json(payload))
            elif kind == "status":
                await self._status(who, payload.decode("utf-8", "replace").strip())
            elif kind == "telemetry":
                await self._telemetry(who, Telemetry.model_validate_json(payload))
            elif kind == "event":
                await self._event(who, DeviceEvent.model_validate_json(payload))
            elif kind == "health":
                await self._health(who, DeviceHealth.model_validate_json(payload))
        except (ValidationError, ServiceError) as e:
            # Message invalide ou usurpant un autre boîtier : jamais stocké, tracé (signal cyber)
            self.rejected += 1
            detail = e.detail if isinstance(e, ServiceError) else str(e.errors(include_url=False, include_input=False))[:300]
            log.warning("Message %s rejeté : %s", topic, detail)
            if self.rejected <= 20 or self.rejected % 100 == 0:
                await self.repo.audit("mqtt", "message_rejected", topic, {"reason": detail, "total": self.rejected})

    @staticmethod
    def _owner(topic_device: str, payload_device: str) -> None:
        if topic_device != payload_device:
            raise ServiceError(400, f"device_id {payload_device!r} différent du topic {topic_device!r}")

    async def _telemetry(self, topic_device: str, t: Telemetry) -> None:
        self._owner(topic_device, t.device_id)
        if await self.repo.insert_telemetry(t):  # un doublon (tampon rejoué deux fois) n'est ni stocké ni rediffusé
            self.hub.publish("telemetry", t.model_dump())

    async def _event(self, topic_device: str, e: DeviceEvent) -> None:
        self._owner(topic_device, e.device_id)
        if not await self.repo.insert_event(e):
            return
        self.hub.publish("event", e.model_dump())
        if e.type == "tamper":  # l'effraction est un incident à part entière, même sans Brain
            await self.raise_alert(AlertIn(
                device_id=e.device_id, source="edge", domain="physical", type="sabotage", severity="critical",
                score=90, ts=e.ts, explanation="Effraction : manipulation du couvercle du boîtier détectée.",
                factors=[{"name": "tamper_touch", "value": float(e.value) if isinstance(e.value, (int, float)) else 1, "contribution": 1}],
                details=e.details,
            ))

    async def _health(self, topic_device: str, h: DeviceHealth) -> None:
        self._owner(topic_device, h.device_id)
        await self.repo.insert_health(h)
        self.hub.publish("health", h.model_dump())

    async def _status(self, topic_device: str, value: str) -> None:
        if value not in ("online", "offline"):
            raise ServiceError(400, f"statut inconnu {value!r}")
        ts = time.time()
        await self.repo.set_status(topic_device, value, ts)
        self.hub.publish("status", DeviceStatus(device_id=topic_device, status=value, ts=ts).model_dump())  # type: ignore[arg-type]

    async def _score(self, s: Scores) -> None:
        self.last_score_ts = time.time()
        await self.repo.insert_score(s)
        self.hub.publish("score", s.out())

    # ---------------------------------------------------------------------------------------------- incidents
    async def raise_alert(self, a: AlertIn) -> dict[str, Any]:
        alert, is_new = await self.repo.upsert_alert(a)
        self.hub.publish("alert", alert)
        profile = (await self.repo.latest_config() or {}).get("profile", {})
        cooldown = profile.get("brain", {}).get("cooldown_s", 60)
        url = profile.get("integrations", {}).get("webhook_url") or self.settings.webhook_url
        if url and a.severity != "info":
            # Nouvel incident : notifié tout de suite ; répétition : seulement après le délai minimal (brain.cooldown_s)
            due = await self.repo.mark_notified(alert["id"], 0 if is_new else cooldown)
            if due:
                asyncio.create_task(self._webhook(url, alert))
        return alert

    async def _webhook(self, url: str, alert: dict[str, Any]) -> None:
        if not url.startswith(("http://", "https://")):
            return

        def post() -> None:
            req = urllib.request.Request(
                url, data=json.dumps(alert).encode(), headers={"Content-Type": "application/json"}, method="POST"
            )
            urllib.request.urlopen(req, timeout=5).close()  # noqa: S310 (schéma vérifié ci-dessus)

        try:
            await asyncio.to_thread(post)
        except Exception as e:  # une supervision externe en panne ne doit pas gêner l'API
            log.warning("Webhook en échec : %s", e)

    # ---------------------------------------------------------------------------- commandes et configuration
    async def send_command(self, cmd: CommandIn, actor: str) -> dict[str, Any]:
        config = await self.repo.latest_config()
        if not config or cmd.device_id not in config["profile"]["devices"]:
            raise ServiceError(404, f"boîtier inconnu : {cmd.device_id}")
        try:
            body = cmd.payload()
        except ValueError as e:
            raise ServiceError(422, str(e)) from e
        payload = {"id": str(uuid.uuid4()), "ts": time.time(), **body}  # le boîtier ignore une commande de plus de 30 s
        if not self.mqtt or not self.mqtt.connected or not self.mqtt.publish(f"sentinel/{cmd.device_id}/cmd", payload):
            raise ServiceError(503, "broker MQTT indisponible : commande non envoyée")
        await self.repo.insert_command(cmd.device_id, payload, actor)
        await self.repo.audit(actor, "command", cmd.device_id, body)
        return payload

    async def save_config(self, profile: SiteProfile, actor: str) -> dict[str, Any]:
        try:
            profile.checked()
        except ValueError as e:
            raise ServiceError(422, str(e)) from e
        saved = await self.repo.insert_config(profile.out(), actor)
        await self.repo.sync_device_labels(saved["profile"]["devices"])
        await self.repo.audit(actor, "config_update", f"version {saved['version']}")
        if not self.publish_config(saved["profile"]):
            log.warning("Broker indisponible : le profil v%s sera republié à la reconnexion", saved["version"])
        return saved

    # ------------------------------------------------------------------------------------------------ santé
    async def health(self) -> dict[str, Any]:
        now = time.time()
        db_ok = await self.repo.db.ping()
        mqtt_ok = bool(self.mqtt and self.mqtt.connected)
        brain_age = now - self.last_score_ts if self.last_score_ts else None
        services = [
            {"name": "API", "ok": True, "detail": f"{self.hub.count} dashboard(s) connecté(s)"},
            {"name": "PostgreSQL", "ok": db_ok, "detail": None if db_ok else "injoignable"},
            {"name": "Mosquitto (MQTT)", "ok": mqtt_ok, "detail": None if mqtt_ok else "déconnecté"},
            {"name": "Sentinel Brain", "ok": brain_age is not None and brain_age < 15,
             "detail": "aucun score reçu" if brain_age is None else f"dernier score il y a {int(brain_age)} s"},
        ]
        vision = None
        if self.settings.vision_health_url:
            vision, detail = await asyncio.to_thread(self._vision_health)
            services.append({"name": "Vision", "ok": vision is not None, "detail": detail})
        mem = psutil.virtual_memory()
        return {
            "ts": now,
            "server": {"cpu_pct": psutil.cpu_percent(interval=None), "mem_pct": mem.percent,
                       "uptime_s": int(now - psutil.boot_time())},
            "services": services,
            "vision": vision,
            "devices": await self.repo.latest_health() if db_ok else [],
        }

    def _vision_health(self) -> tuple[dict[str, float] | None, str]:
        try:
            with urllib.request.urlopen(self.settings.vision_health_url, timeout=2) as r:  # noqa: S310 (URL de la stack)
                body = json.loads(r.read() or b"{}")
            fps, lat = body.get("fps"), body.get("latency_ms")
            return ({"fps": float(fps), "latency_ms": float(lat)} if fps is not None and lat is not None else None), "hors Docker"
        except Exception as e:
            return None, f"injoignable ({type(e).__name__})"

    # ------------------------------------------------------------------------------------------------ purge
    async def purge_forever(self) -> None:
        while True:
            try:
                async with self.repo.db.conn() as c:
                    for table, days in RETENTION_DAYS.items():
                        cur = await c.execute(f"DELETE FROM {table} WHERE ts < now() - make_interval(days => %s)", (days,))  # noqa: S608 (noms de tables constants)
                        if cur.rowcount:
                            log.info("Purge : %s lignes supprimées de %s", cur.rowcount, table)
            except Exception:
                log.exception("Purge impossible")
            await asyncio.sleep(3600)
