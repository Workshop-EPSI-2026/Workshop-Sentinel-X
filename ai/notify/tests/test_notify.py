"""Tests des notifications, sans broker, sans haut-parleur et sans serveur de mail.

    python -m unittest discover -s ai/notify/tests -v
"""
from __future__ import annotations

import sys
import unittest
from email import message_from_bytes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.mailer import SmtpConfig, build  # noqa: E402
from app.rules import AlertRules, CameraWatch, Settings, fmt_duration, route_alert  # noqa: E402
from app.speech import command  # noqa: E402


def alert(kind="intrusion_confirmed", sev="critical", device="cam-01", **kw):
    return {"device_id": device, "source": "brain", "domain": "physical", "type": kind, "severity": sev,
            "score": 95, "eta_min": None, "ts": 1_791_300_000, "explanation": "Personne sans badge dans la zone",
            **kw}


class AlertRulesTest(unittest.TestCase):
    def test_intrusion_is_spoken_with_photo(self):
        n = AlertRules(Settings()).on_alert(alert(), 100.0)
        self.assertEqual(n.spoken, "Intrus détecté.")
        self.assertEqual(n.photo, "now")
        self.assertIn("CRITIQUE", n.subject)

    def test_repeat_is_silenced_during_cooldown_but_escalation_passes(self):
        r = AlertRules(Settings(cooldown_s=120))
        self.assertIsNotNone(r.on_alert(alert(kind="gas_leak", sev="warning"), 0))
        self.assertIsNone(r.on_alert(alert(kind="gas_leak", sev="warning"), 60))       # répétition
        self.assertIsNotNone(r.on_alert(alert(kind="gas_leak", sev="critical"), 70))   # gravité qui monte
        self.assertIsNotNone(r.on_alert(alert(kind="gas_leak", sev="critical"), 200))  # après le délai

    def test_info_and_unknown_types_are_ignored(self):
        r = AlertRules(Settings())
        self.assertIsNone(r.on_alert(alert(kind="presence_authorized", sev="info"), 0))
        self.assertIsNone(r.on_alert(alert(kind="camera_degraded", sev="warning"), 0))

    def test_gas_alert_has_no_photo_and_shows_eta(self):
        n = AlertRules(Settings()).on_alert(alert(kind="gas_leak", device="esp-01", eta_min=3.0), 0)
        self.assertIsNone(n.photo)
        self.assertTrue(any("3.0 min" in x for x in n.lines))

    def test_profile_settings(self):
        s = Settings.from_profile({"notifications": {"voice": False, "recipients": ["a@b.fr"], "cooldown_s": 30}})
        self.assertFalse(s.voice)
        self.assertEqual(s.recipients, ["a@b.fr"])
        self.assertEqual(s.cooldown_s, 30)
        self.assertIn("intrusion_confirmed", s.types)


class CameraWatchTest(unittest.TestCase):
    def test_masked_then_restored_with_duration(self):
        w = CameraWatch(Settings(camera_masked_s=2, camera_restored_s=3))
        msg = lambda m: {"device_id": "cam-01", "masked": m}  # noqa: E731
        self.assertIsNone(w.on_vision(msg(False), 0))
        self.assertIsNone(w.on_vision(msg(True), 10))
        self.assertIsNone(w.on_vision(msg(True), 11))             # pas encore 2 s
        n = w.on_vision(msg(True), 12.5)
        self.assertEqual((n.kind, n.photo), ("camera_masked", "before_mask"))
        self.assertTrue(w.is_masked("cam-01"))
        self.assertIsNone(w.on_vision(msg(True), 30))             # toujours masquée : rien de nouveau
        self.assertIsNone(w.on_vision(msg(False), 40))
        n = w.on_vision(msg(False), 43.2)
        self.assertEqual(n.kind, "camera_restored")
        self.assertIn("31 s", n.lines[0])                         # masquée de 12,5 s à 43,2 s

    def test_flicker_does_not_notify(self):
        w = CameraWatch(Settings(camera_masked_s=2))
        for t, m in ((0, True), (1, False), (2, True), (3, False), (4, True), (5, False)):
            self.assertIsNone(w.on_vision({"device_id": "cam-01", "masked": m}, t))

    def test_brain_masking_alert_becomes_camera_masked_then_restored(self):
        rules, w = AlertRules(Settings()), CameraWatch(Settings(camera_restored_s=3))
        sab = alert(kind="sabotage", explanation="Caméra masquée : image uniforme depuis 0 s")
        n = route_alert(rules, w, sab, 100)
        self.assertEqual((n.kind, n.spoken, n.photo), ("camera_masked", "Caméra masquée.", "before_mask"))
        self.assertIsNone(route_alert(rules, w, sab, 101))                       # pas deux fois
        self.assertIsNone(w.on_vision({"device_id": "cam-01", "masked": True}, 102))   # la vision confirme : rien
        self.assertIsNone(w.on_vision({"device_id": "cam-01", "masked": False}, 110))
        n = w.on_vision({"device_id": "cam-01", "masked": False}, 113)
        self.assertEqual(n.kind, "camera_restored")
        self.assertIn("13 s", n.lines[0])

    def test_box_tamper_stays_sabotage(self):
        n = route_alert(AlertRules(Settings()), CameraWatch(Settings()),
                        alert(kind="sabotage", device="esp-01", explanation="Ouverture du boîtier"), 0)
        self.assertEqual(n.spoken, "Sabotage détecté.")

    def test_duration_format(self):
        self.assertEqual(fmt_duration(75), "1 min 15 s")
        self.assertEqual(fmt_duration(9.6), "10 s")


class MailTest(unittest.TestCase):
    def test_mail_has_text_html_inline_and_attached_photo(self):
        jpg = b"\xff\xd8\xff\xe0fake-jpeg\xff\xd9"
        msg = build("CRITIQUE — Intrus détecté", ["Personne sans badge"], "06/10/2026 21:42:10", "Démo EPSI",
                    "alertes@exemple.fr", ["proprio@exemple.fr"], jpg, "Image au moment de l'alerte", "20261006-214210")
        parsed = message_from_bytes(msg.as_bytes())
        self.assertIn("Intrus détecté", str(msg["Subject"]))
        self.assertIn("06/10/2026 21:42:10", str(msg["Subject"]))
        types = [p.get_content_type() for p in parsed.walk()]
        self.assertIn("text/plain", types)
        self.assertIn("text/html", types)
        self.assertGreaterEqual(types.count("image/jpeg"), 2)     # dans le corps HTML et en pièce jointe
        html = next(p for p in parsed.walk() if p.get_content_type() == "text/html").get_payload(decode=True)
        self.assertIn(b"cid:", html)

    def test_smtp_config_from_env(self):
        c = SmtpConfig.from_env({"SMTP_HOST": "smtp.gmail.com", "SMTP_USER": "x@gmail.com",
                                 "NOTIFY_TO": "a@b.fr; c@d.fr"})
        self.assertTrue(c.ready)
        self.assertEqual(c.sender, "x@gmail.com")
        self.assertEqual(c.to, ("a@b.fr", "c@d.fr"))
        self.assertFalse(SmtpConfig.from_env({}).ready)


class SpeechTest(unittest.TestCase):
    def test_windows_command_escapes_quotes_and_prefers_french_voice(self):
        cmd = command("Risque d'incendie.", repeat=2, platform="win32")
        self.assertEqual(cmd[0], "powershell")
        self.assertIn("Risque d''incendie.", cmd[-1])
        self.assertIn("fr*", cmd[-1])
        self.assertIn("$i -lt 2", cmd[-1])


if __name__ == "__main__":
    unittest.main()
