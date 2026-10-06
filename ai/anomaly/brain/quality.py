"""Couche 1 : qualité et intégrité des données.

Avant toute détection, chaque message est contrôlé. Un message rejeté n'alimente jamais les couches 2 à 4 :
un attaquant ne peut ni fausser les lignes de base ni déclencher de fausse alerte environnementale.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

REQUIRED = ("device_id", "seq", "boot_id", "ts", "temp_c", "hum_pct", "gas_mv", "gas_ratio", "pir")
RANGES = {"temp_c": (0.0, 50.0), "hum_pct": (20.0, 90.0), "gas_mv": (0.0, 2500.0), "gas_ratio": (0.0, 10.0)}


@dataclass
class QualityResult:
    ok: bool = True                      # utilisable par les couches 2 à 4
    buffered: bool = False               # mesure ancienne renvoyée après une coupure (replay=true légitime)
    replay_attack: bool = False          # seq déjà vu pour ce boot_id : message rejoué
    stale: bool = False                  # horodatage trop vieux ou dans le futur sans replay=true
    sensor_fault: str | None = None      # capteur figé ou valeur impossible
    gap: int = 0                         # messages manquants depuis le précédent
    reboot: bool = False
    issues: list[str] = field(default_factory=list)


class _DeviceState:
    def __init__(self, memory: int):
        self.boot_id: str | None = None
        self.max_seq = 0
        self.seen: set[int] = set()
        self.order: deque[int] = deque(maxlen=memory)
        self.last_gas_mv: int | None = None
        self.same_gas = 0

    def remember(self, seq: int) -> None:
        if len(self.order) == self.order.maxlen:
            self.seen.discard(self.order[0])
        self.order.append(seq)
        self.seen.add(seq)


class DataQuality:
    def __init__(self, max_skew_s: float = 120.0, frozen_n: int = 30, memory: int = 20000):
        self.max_skew_s = max_skew_s     # écart toléré entre horodatage et réception (messages en direct)
        self.frozen_n = frozen_n         # nombre de lectures MQ-2 identiques avant « capteur figé »
        self.memory = memory             # seq mémorisés par boîtier (> tampon PSRAM de 4000 mesures)
        self.devices: dict[str, _DeviceState] = {}

    def _state(self, device: str) -> _DeviceState:
        return self.devices.setdefault(device, _DeviceState(self.memory))

    def check_sequence(self, msg: dict, rx_ts: float, res: QualityResult) -> None:
        """Contrôles communs à la télémétrie et aux événements (ils partagent le même compteur seq)."""
        st = self._state(str(msg.get("device_id")))
        boot, seq = str(msg.get("boot_id")), int(msg.get("seq", -1))
        if boot != st.boot_id:
            res.reboot = st.boot_id is not None
            st.boot_id, st.max_seq = boot, 0
            st.seen.clear()
            st.order.clear()
        if seq in st.seen:
            res.replay_attack = True
            res.ok = False
            res.issues.append(f"seq {seq} déjà reçu (boot {boot}) : message rejoué")
            return
        if seq > st.max_seq + 1 and st.max_seq:
            res.gap = seq - st.max_seq - 1
        st.max_seq = max(st.max_seq, seq)
        st.remember(seq)
        skew = rx_ts - float(msg.get("ts", rx_ts))
        if not res.buffered and (skew > self.max_skew_s or skew < -self.max_skew_s):
            res.stale = True
            res.ok = False
            res.issues.append(f"horodatage décalé de {skew:+.0f} s sans replay=true")

    def check_telemetry(self, msg: dict, rx_ts: float) -> QualityResult:
        res = QualityResult(buffered=bool(msg.get("replay", False)))
        missing = [k for k in REQUIRED if k not in msg]
        if missing:
            res.ok = False
            res.issues.append("champs manquants : " + ", ".join(missing))
            return res
        self.check_sequence(msg, rx_ts, res)
        if not res.ok:
            return res
        for k, (lo, hi) in RANGES.items():
            v = msg[k]
            if not isinstance(v, (int, float)) or not lo <= v <= hi:
                res.ok = False
                res.sensor_fault = f"{k}={v} hors plage [{lo}, {hi}]"
        st = self._state(str(msg["device_id"]))
        gas = int(msg["gas_mv"])
        st.same_gas = st.same_gas + 1 if gas == st.last_gas_mv else 0
        st.last_gas_mv = gas
        if st.same_gas >= self.frozen_n:          # le MQ-2 est toujours un peu bruité : figé = débranché
            res.ok = False
            res.sensor_fault = f"MQ-2 figé à {gas} mV depuis {st.same_gas} lectures"
        if res.sensor_fault:
            res.issues.append(res.sensor_fault)
        return res
