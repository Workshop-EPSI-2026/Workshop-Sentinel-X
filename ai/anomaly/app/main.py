"""Service Sentinel Brain (tâche je3) : branche le moteur sur le broker MQTT et sur l'API.

    python -m app.main                       # dans le conteneur anomaly (variables d'environnement)
    python -m app.main --env ../../infra/.env --host localhost --port 1883   # sur un poste, pour tester

Entrées  : sentinel/+/telemetry|event|health|status|vision, sentinel/site/config (profil, à chaud),
           journal de Mosquitto (accès refusés -> signaux cyber).
Sorties  : sentinel/brain/score (chaque mesure), sentinel/brain/alert (chaque alerte),
           POST {API_URL}/api/v1/alerts avec la clé d'API (file d'attente bornée, nouvel essai si l'API est absente).
Santé    : fichier /tmp/brain.alive touché toutes les 5 s (contrôle de santé Docker).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import signal
import sys
import threading
import time
from collections import deque
from pathlib import Path

import httpx
import paho.mqtt.client as mqtt
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from brain import SentinelBrain  # noqa: E402

log = logging.getLogger("brain")
SUBSCRIPTIONS = [("sentinel/+/telemetry", 0), ("sentinel/+/event", 1), ("sentinel/+/health", 0),
                 ("sentinel/+/status", 1), ("sentinel/+/vision", 0), ("sentinel/site/config", 1)]
# Lignes du journal de Mosquitto 2.0 qui signalent un accès refusé
DENIED = re.compile(r"not authori[sz]ed|bad user ?name or password|Denied (?:PUBLISH|SUBSCRIBE)|"
                    r"OpenSSL Error|protocol error|Client connection from \S+ failed", re.I)
IP = re.compile(r"(\d{1,3}(?:\.\d{1,3}){3})")
NEW_CONN = re.compile(r"New connection from (\d{1,3}(?:\.\d{1,3}){3})")


def env(name: str, default: str | None = None) -> str | None:
    v = os.environ.get(name)
    return v if v not in (None, "") else default


def load_env_file(path: str) -> None:
    """Lit un fichier .env (KEY=VALUE) sans écraser les variables déjà définies."""
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.split(" #")[0].strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def load_profile(path: str | None) -> dict:
    if path and Path(path).exists():
        return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    log.warning("profil de site introuvable (%s) : valeurs par défaut", path)
    return {}


class AlertSender(threading.Thread):
    """Envoie les alertes à l'API dans l'ordre, sans jamais bloquer la détection."""

    def __init__(self, api_url: str | None, api_key: str | None, maxlen: int = 1000):
        super().__init__(daemon=True, name="alertes")
        self.url = f"{api_url.rstrip('/')}/api/v1/alerts" if api_url else None
        self.headers = {"X-API-Key": api_key or ""}
        self.queue: deque[dict] = deque(maxlen=maxlen)          # au-delà : on perd les plus anciennes
        self.wake = threading.Event()
        self.stop = threading.Event()
        self.sent = self.failed = 0

    def push(self, alert: dict) -> None:
        if self.url:
            self.queue.append(alert)
            self.wake.set()

    def run(self) -> None:
        delay = 1.0
        with httpx.Client(timeout=5.0) as client:
            while not self.stop.is_set():
                self.wake.wait(5.0)
                self.wake.clear()
                while self.queue and not self.stop.is_set():
                    alert = self.queue[0]
                    try:
                        r = client.post(self.url, json=alert, headers=self.headers)
                        if r.status_code < 300 or r.status_code in (400, 401, 403, 422):
                            self.queue.popleft()                 # refus définitif : on n'insiste pas
                            if r.status_code >= 300:
                                self.failed += 1
                                log.error("API a refusé l'alerte (%s) : %s", r.status_code, r.text[:200])
                            else:
                                self.sent += 1
                            delay = 1.0
                            continue
                        raise httpx.HTTPError(f"HTTP {r.status_code}")
                    except httpx.HTTPError as e:
                        log.warning("API injoignable (%s), nouvel essai dans %.0f s (%d en attente)",
                                    e, delay, len(self.queue))
                        self.stop.wait(delay)
                        delay = min(30.0, delay * 2)


class LogWatcher(threading.Thread):
    """Suit le journal de Mosquitto (comme tail -F) et signale chaque accès refusé à Brain."""

    def __init__(self, path: str, on_denied):
        super().__init__(daemon=True, name="journal-mosquitto")
        self.path, self.on_denied = Path(path), on_denied
        self.stop = threading.Event()

    def run(self) -> None:
        pos, inode, last_ip, warned = None, None, None, False
        while not self.stop.is_set():
            try:
                st = self.path.stat()
                if inode != st.st_ino or (pos is not None and st.st_size < pos):
                    inode, pos = st.st_ino, (st.st_size if pos is None else 0)   # démarrage : fin du fichier
                with self.path.open("r", encoding="utf-8", errors="replace") as f:
                    f.seek(pos)
                    for line in f:
                        new = NEW_CONN.search(line)
                        if new:                     # le refus qui suit ne répète pas l'adresse : on la garde
                            last_ip = new.group(1)
                        elif DENIED.search(line):
                            m = IP.search(line)
                            self.on_denied(self.reason(line), m.group(1) if m else last_ip)
                    pos = f.tell()
            except FileNotFoundError:
                pass
            except PermissionError:
                if not warned:
                    log.warning("journal de Mosquitto illisible (%s) : détection des accès refusés suspendue, "
                                "nouvel essai toutes les 30 s (le service doit tourner sous l'utilisateur 1883)",
                                self.path)
                    warned = True
                self.stop.wait(30)
                continue
            except OSError as e:                     # ne jamais tuer le fil : on réessaie
                log.warning("journal de Mosquitto : %s", e)
                self.stop.wait(5)
                continue
            if warned:
                log.info("journal de Mosquitto lisible : détection des accès refusés active")
                warned = False
            self.stop.wait(0.5)

    @staticmethod
    def reason(line: str) -> str:
        low = line.lower()
        if "bad user" in low or "not authori" in low:
            return "identifiants refusés"
        if "denied" in low:
            return "droits ACL refusés"
        if "openssl" in low or "failed" in low:
            return "erreur TLS ou certificat"
        return "protocole invalide"


class BrainService:
    def __init__(self, a: argparse.Namespace):
        self.a = a
        self.profile_path = env("SITE_PROFILE", a.profile)
        self.brain = SentinelBrain.from_profile(load_profile(self.profile_path))
        self.lock = threading.Lock()                     # callbacks MQTT, journal et horloge partagent Brain
        self.sender = AlertSender(env("API_URL"), env("API_KEY"))
        self.client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                                  client_id=f"sentinel-brain-{os.getpid()}")
        self.stop = threading.Event()
        self.stats = {"messages": 0, "alerts": 0, "scores": 0}

    # ---------------------------------------------------------------- MQTT
    def connect(self) -> None:
        c = self.client
        user = env("MQTT_USER", "anomaly")
        c.username_pw_set(user, env("MQTT_PASSWORD"))
        if (env("MQTT_TLS", "false") or "").lower() in ("1", "true", "yes"):
            c.tls_set(ca_certs=env("MQTT_CA", "/certs/ca.crt"), certfile=env("MQTT_CERT"), keyfile=env("MQTT_KEY"))
        c.on_connect = self.on_connect
        c.on_disconnect = lambda *_: log.warning("déconnecté du broker, reconnexion automatique")
        c.on_message = self.on_message
        c.reconnect_delay_set(1, 30)
        host, port = env("MQTT_HOST", "mosquitto"), int(env("MQTT_PORT", "8884"))
        while not self.stop.is_set():
            try:
                c.connect(host, port, keepalive=30)
                break
            except (OSError, ValueError) as e:
                log.warning("broker %s:%s injoignable (%s), nouvel essai dans 3 s", host, port, e)
                self.stop.wait(3)
        c.loop_start()

    def on_connect(self, client, userdata, flags, rc, props=None) -> None:
        if rc != 0:
            log.error("connexion refusée par le broker : %s (identifiants ? ACL ?)", rc)
            return
        client.subscribe(SUBSCRIPTIONS)
        log.info("connecté, abonné à %d sujets", len(SUBSCRIPTIONS))

    def on_message(self, client, userdata, msg) -> None:
        rx = time.time()
        if msg.topic == "sentinel/site/config":
            return self.reload(msg.payload)
        try:
            with self.lock:
                outs = self.brain.handle(msg.topic, msg.payload, rx)
        except Exception:                                  # un message ne doit jamais arrêter le service
            log.exception("message ignoré sur %s", msg.topic)
            return
        self.stats["messages"] += 1
        self.publish(outs)

    def publish(self, outs: list[dict]) -> None:
        for o in outs:
            if o["kind"] == "score":
                self.client.publish("sentinel/brain/score", json.dumps(o["payload"], ensure_ascii=False), qos=0)
                self.stats["scores"] += 1
            else:
                a = o["payload"]
                self.client.publish("sentinel/brain/alert", json.dumps(a, ensure_ascii=False), qos=1)
                self.sender.push(a)
                self.stats["alerts"] += 1
                log.info("ALERTE %s %s %s : %s", a["severity"], a["device_id"], a["type"], a["explanation"])

    def reload(self, payload: bytes) -> None:
        try:
            text = payload.decode("utf-8")
            profile = json.loads(text) if text.lstrip().startswith("{") else yaml.safe_load(text)
            with self.lock:
                self.brain.update_profile(profile or {})
            log.info("profil de site rechargé (sensibilités, seuils, badges)")
        except (ValueError, yaml.YAMLError, AttributeError) as e:
            log.error("profil de site invalide ignoré : %s", e)

    def on_denied(self, reason: str, source: str | None) -> None:
        with self.lock:
            outs = self.brain.security_event(reason, source, time.time())
        self.publish(outs)

    # ---------------------------------------------------------------- boucle
    def run(self) -> None:
        logging.basicConfig(level=env("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
        logging.getLogger("httpx").setLevel(logging.WARNING)
        log.info("Sentinel Brain démarre (profil %s)", self.profile_path)
        self.sender.start()
        watcher = None
        if env("MOSQUITTO_LOG"):
            watcher = LogWatcher(env("MOSQUITTO_LOG"), self.on_denied)
            watcher.start()
        self.connect()
        alive = Path(env("HEARTBEAT_FILE", "/tmp/brain.alive"))
        last_beat = last_stats = 0.0
        while not self.stop.is_set():
            now = time.time()
            with self.lock:
                outs = self.brain.tick(now)
            self.publish(outs)
            if now - last_beat >= 5:
                try:
                    alive.touch()
                except OSError:
                    pass
                last_beat = now
            if now - last_stats >= 300:
                log.info("en service : %(messages)d messages, %(scores)d scores, %(alerts)d alertes", self.stats)
                last_stats = now
            self.stop.wait(2.0)
        self.client.loop_stop()
        self.client.disconnect()
        self.sender.stop.set()
        if watcher:
            watcher.stop.set()


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Service Sentinel Brain")
    ap.add_argument("--env", help="fichier .env à lire (poste de développement)")
    ap.add_argument("--profile", default="/config/site.yml", help="profil de site si SITE_PROFILE n'est pas défini")
    ap.add_argument("--host", help="remplace MQTT_HOST")
    ap.add_argument("--port", help="remplace MQTT_PORT")
    a = ap.parse_args(argv)
    if a.host:
        os.environ["MQTT_HOST"] = a.host
    if a.port:
        os.environ["MQTT_PORT"] = a.port
    if a.env:
        load_env_file(a.env)
        os.environ.setdefault("MQTT_PASSWORD", os.environ.get("MQTT_ANOMALY_PASSWORD", ""))
    svc = BrainService(a)
    signal.signal(signal.SIGTERM, lambda *_: svc.stop.set())
    signal.signal(signal.SIGINT, lambda *_: svc.stop.set())
    svc.run()


if __name__ == "__main__":
    main()
