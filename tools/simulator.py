#!/usr/bin/env python3
"""
Sentinel-X — simulateur d'Edge Node ESP32-S3 (tâche j1).

Publie sur MQTT exactement ce que publiera le boîtier (contrat : docs/contracts.md v2) :
  sentinel/<id>/telemetry  toutes les 2 s (500 ms en suspicion gaz)
  sentinel/<id>/event      immédiat (boot, pir, gas_do, tamper, mode_change)
  sentinel/<id>/health     toutes les 30 s
  sentinel/<id>/status     online / offline, conservé (dernière volonté = offline)

Scénarios (--scenario) : normal, drift, gas_leak, fire, intrusion, tamper, replay, jamming, all.
Chaque scénario : régime normal (--warmup), anomalie, puis retour au calme.

Exemples :
  # broker local de test (docker run -p 1883:1883 eclipse-mosquitto:2.0 mosquitto -c /mosquitto-no-auth.conf)
  python tools/simulator.py --host localhost --scenario gas_leak

  # PC serveur, socle (1883 authentifié)
  python tools/simulator.py --host localhost --user esp-01 --password '...' --scenario all

  # PC serveur, TLS (8883) ; depuis un autre poste du point d'accès : --host 192.168.137.1
  python tools/simulator.py --host localhost --port 8883 --tls --cafile security/certs/ca.crt \\
      --user esp-01 --password '...'

  # jeu de données étiqueté pour le prototype de Brain, sans broker, instantané et reproductible
  python tools/simulator.py --no-mqtt --scenario all --cooldown 600 --speed 100000 --seed 42 \\
      --csv ai/anomaly/data/simu.csv --rx-log ai/anomaly/data/simu_rx.jsonl
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import signal
import sys
import time
import uuid
from collections import deque
from dataclasses import dataclass, field

try:
    import paho.mqtt.client as mqtt
except ImportError:  # --no-mqtt reste possible sans paho
    mqtt = None

SCENARIOS = ["normal", "drift", "gas_leak", "fire", "intrusion", "tamper", "replay", "jamming"]
FW_VERSION = "sim-1.0"


# --------------------------------------------------------------------------- modèle physique
@dataclass
class Sensors:
    """Valeurs « vraies » de l'environnement, avant les défauts des capteurs."""
    rng: random.Random
    temp: float = 22.0           # °C
    hum: float = 45.0            # %
    gas_mv: float = 420.0        # mV après pont diviseur
    rssi: float = -55.0          # dBm
    pir: bool = False
    pir_times: deque = field(default_factory=deque)

    def step(self, dt: float, t: float) -> None:
        # dérive lente naturelle (variation journalière compressée) + bruit
        self.temp += (22.0 + 0.6 * math.sin(t / 900.0) - self.temp) * min(1.0, dt / 300.0)
        self.temp += self.rng.gauss(0, 0.02)
        self.hum += (45.0 - self.hum) * min(1.0, dt / 600.0) + self.rng.gauss(0, 0.05)
        self.gas_mv += (420.0 - self.gas_mv) * min(1.0, dt / 120.0) + self.rng.gauss(0, 1.0)
        self.rssi += (-55.0 - self.rssi) * min(1.0, dt / 30.0) + self.rng.gauss(0, 0.6)

    def read_dht11(self) -> tuple[float, float]:
        """DHT11 : pas de 1 °C et 1 %, plage 0-50 °C et 20-90 %."""
        t = min(50, max(0, round(self.temp)))
        h = min(90, max(20, round(self.hum)))
        return float(t), float(h)

    def read_gas_mv(self) -> int:
        """Moyenne de 16 lectures, plafonnée par le pont diviseur (2500 mV)."""
        return int(min(2500, max(0, self.gas_mv + self.rng.gauss(0, 1.0))))


# --------------------------------------------------------------------------- scénarios
def anomaly_effect(name: str, s: Sensors, since: float, dt: float, rng: random.Random) -> dict:
    """Applique l'effet du scénario pendant sa phase active. Renvoie des drapeaux."""
    flags: dict = {}
    if name == "drift":                       # panne de climatisation : +0,6 °C/min tant qu'elle dure, gaz stable
        s.temp += 0.6 / 60.0 * dt + (s.temp - 22.0) * min(1.0, dt / 300.0)   # annule le retour naturel à 22 °C
    elif name == "gas_leak":                  # ratio gaz vers 2,2 en ~5 min, température stable
        target = 420.0 * (1.0 + 1.2 * min(1.0, since / 300.0))
        s.gas_mv += (target - s.gas_mv) * min(1.0, dt / 20.0)
    elif name == "fire":                      # température et gaz montent ensemble, humidité baisse
        s.temp += 2.0 / 60.0 * dt * 1.6
        s.hum -= 1.0 / 60.0 * dt
        target = 420.0 * (1.0 + 0.9 * min(1.0, since / 240.0))
        s.gas_mv += (target - s.gas_mv) * min(1.0, dt / 15.0)
    elif name == "intrusion":                 # passages répétés devant le PIR
        flags["pir_rate"] = 0.35
    elif name == "tamper":                    # main sur le couvercle, une fois
        flags["tamper"] = since < dt / 2          # premier pas de la phase seulement
    elif name == "jamming":                   # RSSI qui s'effondre, puis coupure
        s.rssi += (-92.0 - s.rssi) * min(1.0, dt / 25.0)
        flags["offline"] = since > 60.0
    elif name == "replay":
        flags["replay_attack"] = True
    return flags


# --------------------------------------------------------------------------- simulateur
class Simulator:
    def __init__(self, a: argparse.Namespace):
        self.a = a
        self.rng = random.Random(a.seed)
        self.s = Sensors(self.rng)
        self.device = a.device
        self.base = f"sentinel/{self.device}"
        self.boot_id = uuid.UUID(int=self.rng.getrandbits(128)).hex[:8] if a.seed is not None else uuid.uuid4().hex[:8]
        self.seq = 0
        # graine fixée : horloge de départ fixe aussi, pour un jeu de données identique octet pour octet
        self.t0 = 1_790_000_000.0 if a.seed is not None else time.time()
        self.sim_t = 0.0                  # secondes simulées depuis le démarrage
        self.gas_baseline: float | None = None
        self.ewma_gas: float | None = None
        self.mode = "learning"
        self.buffer: deque = deque(maxlen=4000)   # comme le tampon PSRAM du firmware
        self.history: deque = deque(maxlen=200)   # pour le scénario de rejeu
        self.online = True
        self.wifi_disconnects = 0
        self.burst_until = -1.0
        self.last_gas_do = False
        self.client = None
        self.csv_writer = None
        self.csv_file = None
        self.rx_file = None
        self.cur_label = "normal"
        self.plan = self._build_plan()

    # ---- plan de scénarios : liste de (nom, début, fin) en secondes simulées
    def _build_plan(self) -> list[tuple[str, float, float]]:
        names = SCENARIOS[1:] if self.a.scenario == "all" else [self.a.scenario]
        plan, t = [], 0.0
        for n in names:
            t += self.a.warmup
            if n != "normal":
                plan.append((n, t, t + self.a.anomaly))
                t += self.a.anomaly + self.a.cooldown
        self.end_t = t + (self.a.warmup if self.a.scenario != "normal" else 0)
        return plan

    def active(self) -> tuple[str, float] | None:
        for n, start, stop in self.plan:
            if start <= self.sim_t < stop:
                return n, self.sim_t - start
        return None

    def recovering(self) -> str | None:
        """Retour au calme après une anomalie : étiqueté à part pour ne pas fausser l'évaluation."""
        for n, _start, stop in self.plan:
            if stop <= self.sim_t < stop + self.a.cooldown:
                return f"{n}_recovery"
        return None

    # ---- MQTT
    def connect(self) -> None:
        if self.a.no_mqtt:
            return
        if mqtt is None:
            sys.exit("paho-mqtt manquant : pip install 'paho-mqtt>=2.1,<3'")
        c = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                        client_id=f"sim-{self.device}-{self.boot_id}")
        if self.a.user:
            c.username_pw_set(self.a.user, self.a.password)
        if self.a.tls:
            c.tls_set(ca_certs=self.a.cafile, certfile=self.a.cert, keyfile=self.a.key)
        c.will_set(f"{self.base}/status", "offline", qos=1, retain=True)
        c.on_connect = lambda cl, ud, fl, rc, pr: print(f"[mqtt] connecté ({rc})", flush=True)
        c.on_disconnect = lambda cl, ud, fl, rc, pr: print(f"[mqtt] déconnecté ({rc})", flush=True)
        c.reconnect_delay_set(1, 10)
        try:
            c.connect(self.a.host, self.a.port, keepalive=30)
        except (OSError, ValueError) as e:
            sys.exit(f"Broker injoignable sur {self.a.host}:{self.a.port} ({e}). "
                     "Broker démarré ? Bonne adresse ? Bon port (1883, 8883) ?")
        c.loop_start()
        self.client = c
        deadline = time.time() + 10
        while not c.is_connected() and time.time() < deadline:
            time.sleep(0.1)
        if not c.is_connected():
            sys.exit(f"Connexion impossible à {self.a.host}:{self.a.port} (identifiants, TLS ou réseau ?)")
        self.pub("status", "online", qos=1, retain=True, raw=True)

    def pub(self, sub: str, payload, qos: int = 0, retain: bool = False, raw: bool = False) -> None:
        if self.rx_file:   # journal de ce que le broker reçoit, dans l'ordre d'arrivée
            self.rx_file.write(json.dumps({"rx_ts": round(self.t0 + self.sim_t, 3), "topic": f"{self.base}/{sub}",
                                           "payload": payload, "label": self.cur_label},
                                          separators=(",", ":"), ensure_ascii=False) + "\n")
        if self.a.verbose:
            print(f"{self.base}/{sub} {payload if raw else json.dumps(payload, ensure_ascii=False)}", flush=True)
        if self.client is None:
            return
        data = payload if raw else json.dumps(payload, separators=(",", ":"))
        self.client.publish(f"{self.base}/{sub}", data, qos=qos, retain=retain)

    # ---- messages du contrat
    def ts(self) -> int:
        return int(self.t0 + self.sim_t)

    def next_seq(self) -> int:
        self.seq += 1
        return self.seq

    def event(self, etype: str, value=None, details: dict | None = None) -> None:
        msg = {"device_id": self.device, "seq": self.next_seq(), "boot_id": self.boot_id, "ts": self.ts(),
               "type": etype, "value": value, "details": details or {}}
        if self.online:
            self.pub("event", msg, qos=1)

    def health(self) -> None:
        msg = {"device_id": self.device, "ts": self.ts(), "uptime_s": int(self.sim_t),
               "heap_free": 180000 + self.rng.randint(-4000, 4000),
               "psram_free": 7_800_000 - 120 * len(self.buffer), "rssi": int(round(self.s.rssi)),
               "chip_temp_c": round(41.0 + self.rng.gauss(0, 0.5), 1), "reset_reason": "POWERON",
               "buffer_len": len(self.buffer), "wifi_disconnects": self.wifi_disconnects,
               "mqtt_reconnects": self.wifi_disconnects, "tls_errors": 0, "fw_version": FW_VERSION}
        if self.online:
            self.pub("health", msg)

    def telemetry(self, label: str) -> dict:
        temp, hum = self.s.read_dht11()
        gas_mv = self.s.read_gas_mv()
        # ligne de base apprise pendant l'apprentissage (comme le firmware)
        self.ewma_gas = gas_mv if self.ewma_gas is None else 0.95 * self.ewma_gas + 0.05 * gas_mv
        if self.mode == "learning" or self.gas_baseline is None:
            self.gas_baseline = self.ewma_gas
        ratio = round(gas_mv / self.gas_baseline, 3) if self.gas_baseline else 1.0
        gas_do = ratio >= 1.8
        cutoff = self.sim_t - 60
        while self.s.pir_times and self.s.pir_times[0] < cutoff:
            self.s.pir_times.popleft()
        edge = min(100, int(max(0.0, (ratio - 1.0)) * 120 + (25 if self.s.pir else 0)))
        return {"device_id": self.device, "seq": self.next_seq(), "boot_id": self.boot_id, "ts": self.ts(),
                "temp_c": temp, "hum_pct": hum, "gas_mv": gas_mv, "gas_ratio": ratio, "gas_do": gas_do,
                "pir": self.s.pir, "pir_count": len(self.s.pir_times), "mode": self.mode,
                "edge_score": edge, "replay": False, "_label": label}

    def emit_telemetry(self, msg: dict) -> None:
        label = msg.pop("_label")
        self.history.append(dict(msg))
        if self.online:
            self.pub("telemetry", msg)
        else:
            self.buffer.append(msg)
        self.write_csv(msg, label)

    def flush_buffer(self) -> None:
        """Retour du réseau : rejeu du tampon, du plus ancien au plus récent, replay=true."""
        n = len(self.buffer)
        while self.buffer:
            m = self.buffer.popleft()
            m["replay"] = True
            self.pub("telemetry", m)
            if self.client is not None:
                time.sleep(0.02)
        if n:
            print(f"[sim] tampon vidé : {n} mesures renvoyées", flush=True)

    def replay_attack(self) -> None:
        """Attaque : renvoi à l'identique d'anciens messages (même seq, même boot_id)."""
        old = list(self.history)[-20:-10]
        for m in old:
            self.pub("telemetry", m)
        print(f"[sim] rejeu malveillant : {len(old)} anciens messages renvoyés", flush=True)

    # ---- CSV étiqueté
    def open_csv(self) -> None:
        if self.a.rx_log:
            self.rx_file = open(self.a.rx_log, "w", encoding="utf-8")
        if not self.a.csv:
            return
        self.csv_file = open(self.a.csv, "w", newline="", encoding="utf-8")
        cols = ["device_id", "seq", "boot_id", "ts", "temp_c", "hum_pct", "gas_mv", "gas_ratio", "gas_do",
                "pir", "pir_count", "mode", "edge_score", "replay", "rssi", "label"]
        self.csv_writer = csv.DictWriter(self.csv_file, fieldnames=cols)
        self.csv_writer.writeheader()

    def write_csv(self, msg: dict, label: str) -> None:
        if self.csv_writer:
            row = dict(msg, rssi=int(round(self.s.rssi)), label=label)
            self.csv_writer.writerow(row)

    # ---- boucle principale
    def run(self) -> None:
        self.open_csv()
        self.connect()
        self.event("boot", None, {"fw_version": FW_VERSION})
        print(f"[sim] {self.device} boot_id={self.boot_id} scénario={self.a.scenario} "
              f"vitesse x{self.a.speed} plan={[(n, int(s), int(e)) for n, s, e in self.plan]}", flush=True)
        next_tel = next_health = 0.0
        replay_done = set()
        duration = self.a.duration or (self.end_t if self.a.scenario != "normal" else 0)
        tick = 0.5
        try:
            while not duration or self.sim_t < duration:
                act = self.active()
                name, since = (act if act else ("normal", 0.0))
                label = name if act else (self.recovering() or "normal")
                self.cur_label = label
                self.s.step(tick, self.sim_t)
                flags = anomaly_effect(name, self.s, since, tick, self.rng) if act else {}

                # mode apprentissage puis surveillance
                if self.mode == "learning" and self.sim_t >= self.a.learning:
                    self.mode = "armed"
                    self.event("mode_change", "armed")

                # présence
                rate = flags.get("pir_rate", 0.002)
                was = self.s.pir
                self.s.pir = self.rng.random() < rate
                if self.s.pir and not was:
                    self.s.pir_times.append(self.sim_t)
                    self.event("pir", True)
                if flags.get("tamper"):
                    self.event("tamper", True, {"touch_delta": 0.42})

                # brouillage : coupure puis retour avec rejeu du tampon
                if flags.get("offline") and self.online:
                    self.online = False
                    self.wifi_disconnects += 1
                    self.pub("status", "offline", qos=1, retain=True, raw=True)  # ce que la dernière volonté publierait
                    print("[sim] coupure Wi-Fi simulée", flush=True)
                if not flags.get("offline") and not self.online:
                    self.online = True
                    self.pub("status", "online", qos=1, retain=True, raw=True)
                    self.flush_buffer()

                # rejeu malveillant, une fois par scénario
                if flags.get("replay_attack") and name not in replay_done and len(self.history) > 30:
                    self.replay_attack()
                    replay_done.add(name)

                # échantillonnage accéléré si le gaz monte
                ratio_now = self.s.gas_mv / (self.gas_baseline or self.s.gas_mv)
                if ratio_now > 1.25:
                    self.burst_until = self.sim_t + 60
                period = 0.5 if self.sim_t < self.burst_until else self.a.period

                if self.sim_t >= next_tel:
                    msg = self.telemetry(label)
                    if msg["gas_do"] and not self.last_gas_do:
                        self.event("gas_do", True, {"gas_ratio": msg["gas_ratio"]})
                    self.last_gas_do = msg["gas_do"]
                    self.emit_telemetry(msg)
                    next_tel = self.sim_t + period
                if self.sim_t >= next_health:
                    self.health()
                    next_health = self.sim_t + 30

                self.sim_t += tick
                if not self.a.no_mqtt or self.a.speed < 1000:
                    time.sleep(tick / self.a.speed)
        except KeyboardInterrupt:
            print("\n[sim] arrêt demandé", flush=True)
        finally:
            if self.csv_file:
                self.csv_file.close()
                print(f"[sim] CSV écrit : {self.a.csv}", flush=True)
            if self.rx_file:
                self.rx_file.close()
                print(f"[sim] journal de réception écrit : {self.a.rx_log}", flush=True)
            if self.client is not None:
                self.pub("status", "offline", qos=1, retain=True, raw=True)
                time.sleep(0.3)
                self.client.loop_stop()
                self.client.disconnect()
            print(f"[sim] terminé : {self.seq} messages numérotés, {int(self.sim_t)} s simulées", flush=True)


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Simulateur d'Edge Node Sentinel-X (contrat v2)",
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    g = p.add_argument_group("MQTT")
    g.add_argument("--host", default="localhost")
    g.add_argument("--port", type=int, default=1883)
    g.add_argument("--user")
    g.add_argument("--password")
    g.add_argument("--tls", action="store_true", help="TLS (8883 boîtiers, 8884 services)")
    g.add_argument("--cafile", help="ca.crt de la CA locale")
    g.add_argument("--cert", help="certificat client (TLS mutuel)")
    g.add_argument("--key", help="clé du certificat client (TLS mutuel)")
    g.add_argument("--no-mqtt", action="store_true", help="ne publie rien (génération de données seule)")
    s = p.add_argument_group("simulation")
    s.add_argument("--device", default="esp-01")
    s.add_argument("--scenario", choices=SCENARIOS + ["all"], default="normal")
    s.add_argument("--period", type=float, default=2.0, help="période de télémétrie (s), 1 minimum")
    s.add_argument("--warmup", type=float, default=900.0, help="régime normal avant chaque anomalie (s simulées)")
    s.add_argument("--anomaly", type=float, default=300.0, help="durée de chaque anomalie (s simulées)")
    s.add_argument("--cooldown", type=float, default=300.0, help="retour au calme après l'anomalie (s simulées)")
    s.add_argument("--learning", type=float, default=600.0, help="durée du mode apprentissage (s simulées)")
    s.add_argument("--duration", type=float, default=0, help="durée totale (s simulées), 0 = selon le scénario, infini en normal")
    s.add_argument("--speed", type=float, default=1.0, help="accélération du temps (60 = 1 min par seconde)")
    s.add_argument("--seed", type=int, help="graine aléatoire (jeu de données reproductible)")
    s.add_argument("--csv", help="écrit la télémétrie étiquetée dans ce fichier (vue capteurs)")
    s.add_argument("--rx-log", help="écrit en JSONL tout ce que le broker reçoit (vue réseau : rejeux, coupures, "
                                    "événements, santé) ; c'est l'entrée du prototype de Sentinel Brain")
    s.add_argument("-v", "--verbose", action="store_true", help="affiche chaque message")
    a = p.parse_args(argv)
    if a.period < 1.0:
        p.error("--period doit être d'au moins 1 s (limite du DHT11)")
    if a.speed <= 0:
        p.error("--speed doit être positif")
    if a.tls and not a.cafile:
        p.error("--tls exige --cafile")
    return a


def main(argv=None) -> None:
    a = parse_args(argv)
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        Simulator(a).run()
    except KeyboardInterrupt:
        sys.exit("[sim] arrêt avant la connexion au broker")


if __name__ == "__main__":
    main()
