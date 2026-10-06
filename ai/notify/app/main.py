"""Service de notifications de Sentinel-X, sur le PC serveur (haut-parleurs et Internet) :

- alertes de Sentinel Brain (sentinel/brain/alert) : annonce vocale (« Intrus détecté ») et mail aux propriétaires
  du site, avec la photo prise au moment de l'alerte, la date et l'heure ;
- caméra masquée puis rétablie (sentinel/<cam>/vision) : annonce et mail au début (avec la dernière image avant le
  masquage) et à la fin (avec la durée du masquage).

    python -m app.main --env ..\\..\\infra\\.env          # lancé par tools\\demarrer.ps1, depuis ai\\notify
    python -m app.main --env ..\\..\\infra\\.env --tester # essai : une annonce et un mail, puis arrêt

Réglages : section « notifications » du profil de site (rechargée à chaud depuis la page Réglages) et SMTP_* /
NOTIFY_TO dans infra/.env.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import queue
import ssl
import sys
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path

import paho.mqtt.client as mqtt
import yaml

from .mailer import Mailer, SmtpConfig, build
from .rules import AlertRules, CameraWatch, Notice, Settings
from .speech import Speaker

ROOT = Path(__file__).resolve().parents[3]
log = logging.getLogger("notify")


def read_env(path: str | None) -> dict[str, str]:
    values: dict[str, str] = {}
    if path and Path(path).exists():
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                values[k.strip()] = v.split(" #")[0].strip()
    values.update({k: v for k, v in os.environ.items() if k.startswith(("MQTT_", "SMTP_", "NOTIFY_", "VISION_"))})
    return values


class Snapshots:
    """Images de la caméra (service vision, http://127.0.0.1:8001/snapshot.jpg) : l'image actuelle à la demande,
    et la dernière image saine, rafraîchie toutes les 2 s tant que la caméra n'est pas masquée."""

    def __init__(self, url: str, is_masked) -> None:
        self.url, self.is_masked = url.rstrip("/") + "/snapshot.jpg", is_masked
        self.last_good: bytes | None = None
        threading.Thread(target=self._run, daemon=True, name="images").start()

    def now(self) -> bytes | None:
        try:
            with urllib.request.urlopen(self.url, timeout=3) as r:  # noqa: S310 (service local du PC)
                return r.read() if r.status == 200 else None
        except OSError:
            return None

    def _run(self) -> None:
        while True:
            if not self.is_masked():
                img = self.now()
                if img:
                    self.last_good = img
            time.sleep(2)


class NotifyService:
    def __init__(self, a: argparse.Namespace) -> None:
        self.env = read_env(a.env)
        self.profile = self._load_profile(a.profile or self.env.get("SITE_PROFILE_PATH"))
        self.settings = Settings.from_profile(self.profile)
        self.rules, self.camera = AlertRules(self.settings), CameraWatch(self.settings)
        self.smtp = SmtpConfig.from_env(self.env)
        self.speaker = Speaker(enabled=self.settings.voice and self.env.get("NOTIFY_VOICE", "on") != "off")
        self.mailer = Mailer(self.smtp)
        self.images = Snapshots(a.vision_url or self.env.get("VISION_URL", "http://127.0.0.1:8001"),
                                lambda: any(self.camera.is_masked(c) for c in self.camera.state))
        self.work: queue.Queue[Notice] = queue.Queue(maxsize=100)
        self.a = a
        self._mail_reason_logged = ""
        threading.Thread(target=self._worker, daemon=True, name="notifications").start()

    # ------------------------------------------------------------------ profil
    @staticmethod
    def _load_profile(path: str | None) -> dict:
        p = Path(path) if path else ROOT / "config" / "site.example.yml"
        try:
            return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except OSError:
            log.warning("profil de site introuvable (%s) : réglages par défaut", p)
            return {}

    def apply_profile(self, profile: dict) -> None:
        self.profile = profile
        self.settings = Settings.from_profile(profile)
        self.rules.settings = self.camera.settings = self.settings
        self.speaker.enabled = self.settings.voice and self.env.get("NOTIFY_VOICE", "on") != "off"
        log.info("profil rechargé : voix %s, mail %s, destinataires %s", "oui" if self.speaker.enabled else "non",
                 "oui" if self.settings.email else "non", ", ".join(self.recipients()) or "aucun")

    def recipients(self) -> list[str]:
        return self.settings.recipients or list(self.smtp.to)

    def mail_possible(self) -> str:
        """Vide si un mail peut partir, sinon la raison (écrite une fois dans le journal)."""
        if not self.settings.email:
            return "désactivés dans le profil (notifications.email)"
        if not self.smtp.ready:
            return "SMTP non configuré (SMTP_HOST et SMTP_FROM ou SMTP_USER dans infra/.env)"
        if not self.recipients():
            return "aucun destinataire (NOTIFY_TO dans infra/.env ou notifications.recipients du profil)"
        return ""

    # ------------------------------------------------------------------ traitement
    def local_time(self, ts: float) -> tuple[str, str]:
        tz = None
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo((self.profile.get("site") or {}).get("timezone", "Europe/Paris"))
        except Exception:  # noqa: BLE001 (pas de base des fuseaux : heure locale du PC)
            tz = None
        d = datetime.fromtimestamp(ts, tz) if tz else datetime.fromtimestamp(ts)
        return d.strftime("%d/%m/%Y %H:%M:%S"), d.strftime("%Y%m%d-%H%M%S")

    def notify(self, n: Notice) -> None:
        try:
            self.work.put_nowait(n)
        except queue.Full:
            log.error("file des notifications pleine : %s ignorée", n.kind)

    def _worker(self) -> None:
        while True:
            n = self.work.get()
            when, stamp = self.local_time(n.ts)
            log.info("NOTIFICATION %s %s : %s", n.device_id, n.kind, n.lines[0] if n.lines else "")
            self.speaker.say(n.spoken)
            reason = self.mail_possible()
            if reason:
                if reason != self._mail_reason_logged:
                    log.warning("mails non envoyés : %s", reason)
                    self._mail_reason_logged = reason
                continue
            photo, label = None, ""
            if n.photo == "now":
                photo, label = self.images.now(), "Image de la caméra au moment de l'alerte"
            elif n.photo == "before_mask":
                photo, label = self.images.last_good, "Dernière image avant le masquage"
            site = (self.profile.get("site") or {}).get("name", "Sentinel-X")
            self.mailer.send(build(n.subject, n.lines, when, site, self.smtp.sender, self.recipients(), photo, label,
                                   stamp))

    # ------------------------------------------------------------------ MQTT
    def on_message(self, _c, _u, msg) -> None:
        now = time.time()
        try:
            if msg.topic == "sentinel/site/config":
                self.apply_profile(json.loads(msg.payload))
            elif msg.topic == "sentinel/brain/alert":
                n = self.rules.on_alert(json.loads(msg.payload), now)
                if n:
                    self.notify(n)
            elif msg.topic.endswith("/vision"):
                n = self.camera.on_vision(json.loads(msg.payload), now)
                if n:
                    self.notify(n)
        except (ValueError, TypeError) as e:
            log.warning("message %s ignoré : %s", msg.topic, e)

    def connect(self) -> mqtt.Client:
        e = self.env
        host = self.a.host or e.get("MQTT_HOST_PC", "localhost")
        port = int(self.a.port or e.get("MQTT_PORT", "1883"))
        tls = e.get("MQTT_TLS", "false").lower() in ("1", "true", "yes")
        if tls and port == 8884:                 # 8884 = services internes à Docker ; depuis le PC : 8883
            port = 8883
        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"sentinel-notify-{os.getpid()}")
        c.username_pw_set(e.get("MQTT_NOTIFY_USER", "notify"), e.get("MQTT_NOTIFY_PASSWORD", ""))
        if tls:
            c.tls_set(ca_certs=e.get("MQTT_CA", str(ROOT / "security" / "certs" / "ca.crt")),
                      certfile=e.get("MQTT_CERT") or None, keyfile=e.get("MQTT_KEY") or None,
                      tls_version=ssl.PROTOCOL_TLS_CLIENT)
        c.on_message = self.on_message

        def on_connect(cl, _u, _f, rc, _p) -> None:
            if rc.is_failure:
                log.error("connexion au broker refusée : %s (compte notify dans infra/mosquitto/passwd ?)", rc)
                return
            log.info("connecté au broker %s:%s", host, port)
            for topic, qos in (("sentinel/brain/alert", 1), ("sentinel/+/vision", 0), ("sentinel/site/config", 1)):
                cl.subscribe(topic, qos)

        c.on_connect = on_connect
        c.on_disconnect = lambda cl, u, f, rc, p: log.warning("déconnecté du broker (%s)", rc)
        c.reconnect_delay_set(1, 15)
        c.connect_async(host, port, keepalive=30)
        return c

    def run(self) -> int:
        reason = self.mail_possible()
        log.info("notifications : voix %s ; mails %s", "oui" if self.speaker.enabled else "non",
                 "vers " + ", ".join(self.recipients()) if not reason else "non (" + reason + ")")
        c = self.connect()
        c.loop_start()
        try:
            while True:
                time.sleep(300)
                log.info("en service : %d annonces, %d mails envoyés", len(self.speaker.spoken), len(self.mailer.sent))
        except KeyboardInterrupt:
            return 0
        finally:
            c.loop_stop()

    def test(self) -> int:
        """Essai de bout en bout : une annonce et un mail (avec l'image actuelle si la vision tourne)."""
        reason = self.mail_possible()
        self.notify(Notice("test", "cam-01", "warning", "Test Sentinel-X. Intrus détecté.", "TEST — Intrus détecté",
                           ["Ceci est un essai des notifications de Sentinel-X.", "Équipement : cam-01"], time.time(),
                           photo="now"))
        deadline = time.time() + 60
        while time.time() < deadline and (not self.speaker.spoken or (not reason and not self.mailer.sent)):
            time.sleep(0.5)
        print(f"annonce vocale : {'OK' if self.speaker.spoken else 'non'}")
        print(f"mail : {'envoyé à ' + ', '.join(self.recipients()) if self.mailer.sent else 'non envoyé'}"
              + (f" ({reason})" if reason else ""))
        time.sleep(6 if self.speaker.enabled else 0)    # laisser la voix finir avant de quitter
        return 0 if (self.mailer.sent or reason) else 1


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env", help="fichier .env (infra/.env)")
    ap.add_argument("--profile", help="profil de site (défaut : config/site.example.yml)")
    ap.add_argument("--host", help="broker MQTT (défaut : localhost)")
    ap.add_argument("--port", help="port MQTT (défaut : MQTT_PORT du .env)")
    ap.add_argument("--vision-url", help="service vision (défaut : http://127.0.0.1:8001)")
    ap.add_argument("--tester", action="store_true", help="envoie une annonce et un mail d'essai, puis s'arrête")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    svc = NotifyService(a)
    return svc.test() if a.tester else svc.run()


if __name__ == "__main__":
    raise SystemExit(main())
