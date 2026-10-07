"""Tests de Sentinel Brain (bibliothèque standard uniquement).

Lancer depuis la racine du dépôt :  python -m unittest discover -s ai/anomaly/tests -v
"""
from __future__ import annotations

import json
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ANOM = Path(__file__).resolve().parents[1]
ROOT = ANOM.parents[1]
sys.path.insert(0, str(ANOM))

from brain import BrainConfig, SentinelBrain  # noqa: E402
from brain.detectors import Holt, PoissonRate, RobustCusum  # noqa: E402
from brain.quality import DataQuality  # noqa: E402

PARIS = __import__("zoneinfo").ZoneInfo("Europe/Paris")
PROFILE = {"site": {"timezone": "Europe/Paris"},
           "brain": {"correlation_window_s": 5, "loitering_s": 20, "camera_timeout_s": 15},
           "vision": {"authorized_badges": [{"id": 7, "name": "A. Martin", "hours": "07:00-19:00"}]}}


def telem(seq: int, ts: float, **kw) -> dict:
    m = {"device_id": "esp-t", "seq": seq, "boot_id": "b1", "ts": ts, "temp_c": 22.0, "hum_pct": 45.0,
         "gas_mv": 420 + seq % 7, "gas_ratio": 1.0, "gas_do": False, "pir": False, "pir_count": 0,
         "mode": "armed", "edge_score": 0, "replay": False}
    m.update(kw)
    return m


class QualityTest(unittest.TestCase):
    def test_replay_attack_detected(self):
        q = DataQuality()
        self.assertTrue(q.check_telemetry(telem(1, 100), 100).ok)
        r = q.check_telemetry(telem(1, 100), 130)
        self.assertTrue(r.replay_attack)
        self.assertFalse(r.ok)

    def test_buffered_measure_accepted_but_stale_live_rejected(self):
        q = DataQuality()
        q.check_telemetry(telem(1, 1000), 1000)
        self.assertTrue(q.check_telemetry(telem(2, 500, replay=True), 1001).ok)      # tampon après coupure
        self.assertTrue(q.check_telemetry(telem(3, 500), 1002).stale)               # vieux, sans replay=true

    def test_implausible_and_frozen(self):
        q = DataQuality(frozen_n=5)
        self.assertIsNotNone(q.check_telemetry(telem(1, 1, temp_c=80.0), 1).sensor_fault)
        res = [q.check_telemetry(telem(i, i, gas_mv=400), i) for i in range(2, 10)]
        self.assertIn("figé", res[-1].sensor_fault or "")


class DetectorTest(unittest.TestCase):
    def test_cusum_quiet_on_noise_and_detects_shift(self):
        rng = random.Random(1)
        c = RobustCusum("x", k=1.5, h=6, tau_d=60, min_sigma=0.01, warmup_s=600, direction="up")
        alarms = [c.update(1 + rng.gauss(0, 0.02), 2.0 * i).alarm for i in range(3000)]
        self.assertFalse(any(alarms))
        shifted = [c.update(1.15 + rng.gauss(0, 0.02), 6000 + 2.0 * i).alarm for i in range(120)]
        self.assertTrue(any(shifted))

    def test_holt_eta_on_linear_ramp(self):
        h = Holt(tau_level=10, tau_trend=30)
        for i in range(200):                      # +0,2 par minute
            h.update(1.0 + 0.2 * (2 * i) / 60, 2.0 * i)
        eta = h.eta_min(target=3.0, min_slope_per_min=0.01, horizon_min=30)
        real = (3.0 - (1.0 + 0.2 * 398 / 60)) / 0.2
        self.assertAlmostEqual(eta, real, delta=0.3)

    def test_poisson_tail(self):
        self.assertAlmostEqual(PoissonRate.tail(1, 1.0), 1 - 0.36788, places=4)
        self.assertEqual(PoissonRate.tail(0, 1.0), 1.0)


class EndToEndTest(unittest.TestCase):
    """Rejoue de courts scénarios du simulateur (tools/simulator.py) dans Brain."""

    @staticmethod
    def replay(scenario: str) -> list[tuple[float, str, dict]]:
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "rx.jsonl"
            subprocess.run([sys.executable, str(ROOT / "tools" / "simulator.py"), "--no-mqtt", "--speed", "100000",
                            "--seed", "3", "--scenario", scenario, "--warmup", "1500", "--rx-log", str(log)],
                           check=True, capture_output=True)
            brain, out = SentinelBrain(BrainConfig()), []
            for line in log.read_text(encoding="utf-8").splitlines():
                m = json.loads(line)
                out += [(m["rx_ts"], m["label"], o["payload"]) for o in brain.handle(m["topic"], m["payload"],
                                                                                    m["rx_ts"]) if o["kind"] == "alert"]
            return out

    def test_gas_leak_detected_before_raw_threshold(self):
        alerts = self.replay("gas_leak")
        self.assertFalse([a for _, lab, a in alerts if lab == "normal"], "fausse alarme en régime normal")
        leak = [(t, a) for t, lab, a in alerts if a["type"] == "gas_leak"]
        self.assertTrue(leak)
        t0 = 1_790_000_000 + 1500
        first_t, first = leak[0]
        self.assertLess(first_t - t0, 90)              # le seuil brut de 1,3 tombe vers 95 s
        self.assertIsNotNone(first["eta_min"])
        self.assertTrue(any(a["severity"] == "critical" for _, a in leak))

    def test_replay_attack_and_tamper(self):
        self.assertTrue(any(a["type"] == "cyber_attack" for _, _, a in self.replay("replay")))
        self.assertTrue(any(a["type"] == "sabotage" for _, _, a in self.replay("tamper")))


def at(hour: int, minute: int = 0) -> float:
    from datetime import datetime
    return datetime(2026, 10, 6, hour, minute, tzinfo=PARIS).timestamp()


class VisionFusionTest(unittest.TestCase):
    """Fusion caméra + PIR + badges + horaires (règles de docs/architecture.md)."""

    def setUp(self):
        self.brain = SentinelBrain.from_profile(PROFILE)
        self.seq = 0

    def vision(self, t, persons=(), masked=False, low_light=False, seq=None):
        self.seq += 1
        msg = {"device_id": "cam-01", "seq": seq or self.seq, "boot_id": "c1", "ts": t, "fps": 10.0,
               "masked": masked, "low_light": low_light, "brightness": 120,
               "persons": [{"track_id": i, "in_zone": z, "dwell_s": d, "badge": b} for i, z, d, b in persons]}
        return self.brain.handle("sentinel/cam-01/vision", json.dumps(msg), t)

    @staticmethod
    def types(outs):
        return {(o["payload"]["type"], o["payload"]["severity"]) for o in outs if o["kind"] == "alert"}

    def test_intruder_confirmed_by_pir(self):
        t = at(10)
        self.brain.handle("sentinel/esp-01/event", json.dumps(
            {"device_id": "esp-01", "seq": 1, "boot_id": "b", "ts": t, "type": "pir", "value": True}), t)
        self.assertIn(("intrusion_confirmed", "critical"), self.types(self.vision(t + 2, [(3, True, 1.0, None)])))

    def test_intruder_without_pir_then_loitering(self):
        t = at(10)
        self.assertIn(("intrusion_suspected", "warning"), self.types(self.vision(t, [(3, True, 1.0, None)])))
        self.assertIn(("loitering", "warning"), self.types(self.vision(t + 21, [(3, True, 22.0, None)])))

    def test_unknown_person_confirmed_by_vision_alone_after_3s(self):
        t = at(10)
        self.assertIn(("intrusion_suspected", "warning"), self.types(self.vision(t, [(3, True, 0.5, None)])))
        outs = self.vision(t + 3, [(3, True, 3.2, None)])          # toujours là 3 s plus tard, PIR muet
        self.assertIn(("intrusion_confirmed", "critical"), self.types(outs))
        alert = [o["payload"] for o in outs if o["kind"] == "alert"][0]
        self.assertIn("confirmée par la vision", alert["explanation"])
        self.assertEqual(self.types(self.vision(t + 4, [(3, True, 4.2, None)])), set())   # pas de répétition

    def test_vision_confirmation_can_require_pir(self):
        self.brain = SentinelBrain.from_profile({**PROFILE, "brain": {**PROFILE["brain"], "vision_confirm_s": 0}})
        outs = self.vision(at(10), [(3, True, 10.0, None)])
        self.assertIn(("intrusion_suspected", "warning"), self.types(outs))
        self.assertNotIn(("intrusion_confirmed", "critical"), self.types(outs))

    def test_authorized_badge_is_never_an_intruder(self):
        self.assertEqual(self.types(self.vision(at(10), [(1, True, 30.0, 7)])), {("presence_authorized", "info")})

    def test_badge_hours(self):
        self.assertIn(("presence_authorized", "info"), self.types(self.vision(at(10), [(1, True, 2.0, 7)])))
        late = SentinelBrain.from_profile(PROFILE)
        self.brain = late
        self.assertIn(("presence_to_verify", "warning"), self.types(self.vision(at(23), [(1, True, 2.0, 7)])))

    def test_unknown_badge_is_intruder_and_tailgating(self):
        self.assertIn(("intrusion_suspected", "warning"), self.types(self.vision(at(10), [(1, True, 2.0, 99)])))
        b = SentinelBrain.from_profile(PROFILE)
        self.brain = b
        outs = self.vision(at(10), [(1, True, 2.0, 7), (2, True, 2.0, None)])
        alert = [o["payload"] for o in outs if o["kind"] == "alert"][0]
        self.assertEqual(alert["type"], "intrusion_suspected")
        self.assertIn("accompagn", alert["explanation"])

    def test_masked_and_silent_camera(self):
        t = at(10)
        self.assertIn(("sabotage", "critical"), self.types(self.vision(t, masked=True)))
        b = SentinelBrain.from_profile(PROFILE)
        self.brain = b
        self.vision(t, [(3, True, 1.0, None)])                  # quelqu'un, puis plus rien
        self.assertIn(("sabotage", "critical"), self.types(self.brain.tick(t + 20)))

    def test_box_back_online_without_jamming_clears_cyber_score(self):
        b = SentinelBrain(BrainConfig())
        b.handle("sentinel/esp-01/telemetry", json.dumps(telem(1, 1000.0)), 1000.0)
        b.handle("sentinel/esp-01/status", "offline", 1001.0)
        b.handle("sentinel/esp-01/status", "online", 1010.0)
        out = b.handle("sentinel/esp-01/telemetry", json.dumps(telem(2, 1012.0)), 1012.0)
        score = [o["payload"] for o in out if o["kind"] == "score"][0]
        self.assertEqual(score["cyber"], 0)

    def test_camera_offline_without_detection_is_maintenance(self):
        t = at(10)
        self.vision(t)
        self.assertIn(("camera_degraded", "warning"), self.types(self.brain.tick(t + 200)))

    def test_vision_replay_is_cyber(self):
        t = at(10)
        self.vision(t, seq=5)
        self.assertIn(("cyber_attack", "critical"), self.types(self.vision(t + 1, seq=5)))

    def test_refused_mqtt_burst(self):
        out = []
        for i in range(5):
            out += self.brain.security_event("identifiants refusés", "192.168.137.54", 100.0 + i)
        alert = [o["payload"] for o in out if o["kind"] == "alert"][0]
        self.assertEqual((alert["type"], alert["device_id"]), ("cyber_attack", "broker"))
        self.assertIn("192.168.137.54", alert["explanation"])

    def test_profile_reload(self):
        self.brain.handle("sentinel/esp-01/telemetry", json.dumps(telem(1, 1000.0)), 1000.0)
        d = self.brain.devices["esp-01"]
        h0 = d.c_gas.h
        self.brain.update_profile({**PROFILE, "brain": {**PROFILE["brain"], "sensitivity": {"environment": 1.0}}})
        self.assertLess(d.c_gas.h, h0)


if __name__ == "__main__":
    unittest.main()
