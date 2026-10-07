"""Tests de l'API : la porte d'entrée du système (refus, validation, temps réel, messages MQTT).

Sur une vraie PostgreSQL vide (le schéma est recréé à chaque lancement), sans broker MQTT :

    # PostgreSQL de test (Docker) :
    docker run -d --name snx-pg-test -e POSTGRES_USER=sentinel -e POSTGRES_PASSWORD=testpass \\
        -e POSTGRES_DB=sentinel_test -p 55440:5432 postgres:16-alpine
    # depuis la racine du dépôt :
    SENTINEL_TEST_DATABASE_URL=postgresql://sentinel:testpass@127.0.0.1:55440/sentinel_test \\
        python -m unittest discover -s api/tests -v

Sans SENTINEL_TEST_DATABASE_URL, les tests sont ignorés (jamais lancés contre la base de production).
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB_URL = os.environ.get("SENTINEL_TEST_DATABASE_URL", "")
OPERATOR = "op-" + "x" * 40
API_KEY = "svc-" + "y" * 40
logging.disable(logging.WARNING)                     # journaux de l'API muets pendant les tests

if DB_URL:
    os.environ.update({
        "DATABASE_URL": DB_URL, "API_KEY": API_KEY, "OPERATOR_TOKEN": OPERATOR,
        "MQTT_HOST": "127.0.0.1", "MQTT_PORT": "1", "MQTT_TLS": "false",      # pas de broker : l'API doit tenir
        "SITE_PROFILE": str(ROOT / "config" / "site.example.yml"), "VISION_HEALTH_URL": "",
    })
    sys.path.insert(0, str(ROOT / "api"))
    import psycopg
    from app.main import app
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect


def alert(**kw) -> dict:
    a = {"device_id": "cam-01", "source": "brain", "domain": "physical", "type": "intrusion_confirmed",
         "severity": "critical", "score": 95, "eta_min": None, "ts": time.time(),
         "explanation": "Personne sans badge dans la zone depuis 3 s", "factors": [
             {"name": "persons_unauthorized", "value": 1, "contribution": 0.7}]}
    a.update(kw)
    return a


def telemetry(seq: int, device: str = "esp-01", **kw) -> dict:
    t = {"device_id": device, "seq": seq, "boot_id": "b1", "ts": time.time(), "temp_c": 22.5, "hum_pct": 45.0,
         "gas_mv": 400, "gas_ratio": 1.0, "gas_do": False, "pir": False, "pir_count": 0, "mode": "armed",
         "edge_score": 5}
    t.update(kw)
    return t


@unittest.skipUnless(DB_URL, "SENTINEL_TEST_DATABASE_URL non défini : tests de l'API ignorés")
class ApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with psycopg.connect(DB_URL, autocommit=True) as c:      # base vide : migrations rejouées
            c.execute("DROP SCHEMA public CASCADE")
            c.execute("CREATE SCHEMA public")
        cls.ctx = TestClient(app)
        cls.client = cls.ctx.__enter__()
        cls.op = {"Authorization": f"Bearer {OPERATOR}"}
        cls.svc = {"X-API-Key": API_KEY}

    @classmethod
    def tearDownClass(cls):
        cls.ctx.__exit__(None, None, None)

    def mqtt(self, topic: str, payload: dict | bytes) -> None:
        """Message comme s'il arrivait du broker (même chemin que le pont MQTT)."""
        raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.client.portal.call(app.state.core.handle_message, topic, raw)

    def audit(self, action: str) -> list[tuple]:
        with psycopg.connect(DB_URL) as c:
            return c.execute("SELECT actor, target, details FROM audit_log WHERE action = %s", (action,)).fetchall()

    # ------------------------------------------------------------------ refus : sans jeton, mauvais jeton
    def test_operator_routes_refuse_without_or_with_wrong_token(self):
        for method, path in (("GET", "/api/v1/alerts"), ("GET", "/api/v1/score"), ("GET", "/api/v1/config"),
                             ("GET", "/api/v1/telemetry?device=esp-01"), ("PATCH", "/api/v1/alerts/1"),
                             ("POST", "/api/v1/video/ticket"),
                             ("POST", "/api/v1/commands"), ("PUT", "/api/v1/config")):
            for headers in ({}, {"Authorization": "Bearer mauvais"}, {"Authorization": OPERATOR},
                            {"Authorization": f"Bearer {API_KEY}"}):          # la clé des services n'ouvre pas l'interface
                with self.subTest(method=method, path=path, headers=list(headers.values())):
                    r = self.client.request(method, path, headers=headers, json={})
                    self.assertEqual(r.status_code, 401)
                    self.assertEqual(r.headers.get("www-authenticate"), "Bearer")

    def test_service_route_refuses_without_key_or_with_operator_token(self):
        for headers in ({}, {"X-API-Key": "mauvaise"}, {"X-API-Key": OPERATOR}, self.op):
            with self.subTest(headers=list(headers)):
                self.assertEqual(self.client.post("/api/v1/alerts", json=alert(), headers=headers).status_code, 401)

    def test_refusals_are_audited_as_cyber_signal(self):
        time.sleep(1.1)                                   # une ligne d'audit par seconde au plus
        self.client.get("/api/v1/alerts", headers={"Authorization": "Bearer intrus", "X-Real-IP": "192.168.137.66"})
        rows = self.audit("auth_refused")
        self.assertTrue(any(r[2].get("ip") == "192.168.137.66" for r in rows))

    def test_health_hides_details_without_token(self):
        r = self.client.get("/api/v1/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(set(r.json()), {"status", "ts"})
        full = self.client.get("/api/v1/health", headers=self.op).json()
        self.assertIn("services", full)
        self.assertIn("server", full)

    def test_docs_do_not_leak_secrets(self):
        spec = self.client.get("/api/openapi.json").text
        self.assertNotIn(OPERATOR, spec)
        self.assertNotIn(API_KEY, spec)

    def test_video_requires_a_fresh_ticket_from_the_operator(self):
        self.assertEqual(self.client.post("/api/v1/video/ticket").status_code, 401)
        ticket = self.client.post("/api/v1/video/ticket", headers=self.op).json()["ticket"]
        self.assertNotIn(OPERATOR, ticket)

        def check(uri: str) -> int:
            return self.client.get("/api/v1/video/check", headers={"X-Original-URI": uri}).status_code

        self.assertEqual(check(f"/video?ticket={ticket}"), 204)
        self.assertEqual(check("/video"), 401)
        self.assertEqual(check(f"/video?token={OPERATOR}"), 401)
        exp, sig = ticket.split(".")
        self.assertEqual(check(f"/video?ticket={int(exp) + 3600}.{sig}"), 401)          # expiration rallongée
        self.assertEqual(check(f"/video?ticket={exp}.{'0' * len(sig)}"), 401)           # signature forgée
        self.assertEqual(check(f"/video?ticket={int(time.time()) - 1}.{sig}"), 401)     # expiré

    # ------------------------------------------------------------------ accès autorisés
    def test_alert_ingest_then_operator_workflow(self):
        r = self.client.post("/api/v1/alerts", json=alert(), headers=self.svc)
        self.assertEqual(r.status_code, 201, r.text)
        alert_id = r.json()["id"]
        listed = self.client.get("/api/v1/alerts", headers=self.op).json()
        self.assertTrue(any(a["id"] == alert_id for a in listed))
        r = self.client.patch(f"/api/v1/alerts/{alert_id}", json={"status": "acknowledged"}, headers=self.op)
        self.assertEqual((r.status_code, r.json()["status"]), (200, "acknowledged"))
        self.assertTrue(self.audit("alert_acknowledged"))

    def test_sql_injection_is_stored_as_text(self):
        evil = "x'); DROP TABLE alerts; --"
        r = self.client.post("/api/v1/alerts", json=alert(type="sabotage", explanation=evil), headers=self.svc)
        self.assertEqual(r.status_code, 201, r.text)
        self.assertTrue(any(a["explanation"] == evil for a in self.client.get("/api/v1/alerts", headers=self.op).json()))

    # ------------------------------------------------------------------ messages invalides (REST)
    def test_invalid_alerts_are_rejected(self):
        cases = {
            "type inconnu": alert(type="party"),
            "gravité inconnue": alert(severity="apocalypse"),
            "score hors bornes": alert(score=250),
            "champ en trop": alert(admin=True),
            "explication vide": alert(explanation=""),
            "explication géante": alert(explanation="A" * 5000),
            "équipement forgé": alert(device_id="../../etc/passwd"),
            "trop de facteurs": alert(factors=[{"name": "f", "value": 1, "contribution": 0.1}] * 11),
        }
        for name, body in cases.items():
            with self.subTest(name):
                self.assertEqual(self.client.post("/api/v1/alerts", json=body, headers=self.svc).status_code, 422)
        r = self.client.post("/api/v1/alerts", content=b"{pas du json", headers={**self.svc, "Content-Type": "application/json"})
        self.assertEqual(r.status_code, 422)

    def test_invalid_operator_requests_are_rejected(self):
        self.assertEqual(self.client.patch("/api/v1/alerts/1", json={"status": "deleted"}, headers=self.op).status_code, 422)
        self.assertEqual(self.client.patch("/api/v1/alerts/999999", json={"status": "resolved"}, headers=self.op).status_code, 404)
        self.assertEqual(self.client.get("/api/v1/telemetry?device=ESP;DROP", headers=self.op).status_code, 422)
        self.assertEqual(self.client.post("/api/v1/commands", json={"device_id": "esp-01", "cmd": "shell"},
                                          headers=self.op).status_code, 422)
        self.assertEqual(self.client.post("/api/v1/commands", json={"device_id": "esp-01", "cmd": "led"},
                                          headers=self.op).status_code, 422)            # couleur manquante
        self.assertEqual(self.client.post("/api/v1/commands", json={"device_id": "esp-99", "cmd": "reboot"},
                                          headers=self.op).status_code, 404)            # boîtier inconnu

    def test_command_without_broker_is_refused_not_lost_silently(self):
        r = self.client.post("/api/v1/commands", json={"device_id": "esp-01", "cmd": "alarm", "on": False}, headers=self.op)
        self.assertEqual(r.status_code, 503)

    def test_config_validation_and_versioning(self):
        cfg = self.client.get("/api/v1/config", headers=self.op).json()
        profile = cfg["profile"]
        bad = json.loads(json.dumps(profile))
        key = next(iter(bad["thresholds"]))
        bad["thresholds"][key] = {"warning": 90, "critical": 10}
        self.assertEqual(self.client.put("/api/v1/config", json={"profile": bad}, headers=self.op).status_code, 422)
        bad = json.loads(json.dumps(profile))
        bad["brain"]["vision_confirm_s"] = 999
        self.assertEqual(self.client.put("/api/v1/config", json={"profile": bad}, headers=self.op).status_code, 422)
        good = json.loads(json.dumps(profile))
        good["brain"]["vision_confirm_s"] = 2
        r = self.client.put("/api/v1/config", json={"profile": good}, headers=self.op)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["version"], cfg["version"] + 1)
        self.assertEqual(r.json()["profile"]["brain"]["vision_confirm_s"], 2)

    # ------------------------------------------------------------------ temps réel (WebSocket)
    def test_websocket_refuses_missing_or_wrong_token(self):
        for first in ({"type": "auth", "token": "mauvais"}, {"type": "hello"}, {"token": OPERATOR}):
            with self.subTest(first=first), self.client.websocket_connect("/ws") as ws:
                ws.send_text(json.dumps(first))
                with self.assertRaises(WebSocketDisconnect) as e:
                    ws.receive_json()
                self.assertEqual(e.exception.code, 4401)

    def test_websocket_with_token_receives_live_alerts(self):
        with self.client.websocket_connect("/ws") as ws:
            ws.send_text(json.dumps({"type": "auth", "token": OPERATOR}))
            self.assertEqual(ws.receive_json()["type"], "ready")
            self.client.post("/api/v1/alerts", json=alert(type="loitering", severity="warning"), headers=self.svc)
            for _ in range(10):
                msg = ws.receive_json()
                if msg["type"] == "alert":
                    break
            self.assertEqual(msg["data"]["type"], "loitering")

    # ------------------------------------------------------------------ messages MQTT des boîtiers
    def test_valid_telemetry_is_stored(self):
        self.mqtt("sentinel/esp-07/telemetry", telemetry(1, "esp-07", temp_c=23.4))
        items = self.client.get("/api/v1/telemetry?device=esp-07", headers=self.op).json()["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["temp_c"], 23.4)

    def test_invalid_or_spoofed_mqtt_messages_are_rejected_and_audited(self):
        before = app.state.core.rejected
        self.mqtt("sentinel/esp-08/telemetry", b"\xff pas du json")
        self.mqtt("sentinel/esp-08/telemetry", telemetry(1, "esp-08", temp_c=999))            # hors bornes
        self.mqtt("sentinel/esp-08/telemetry", telemetry(2, "esp-09"))                        # se fait passer pour un autre
        self.mqtt("sentinel/esp-08/event", {"device_id": "esp-08", "seq": 3, "boot_id": "b", "ts": time.time(),
                                            "type": "rm -rf"})
        self.assertEqual(app.state.core.rejected - before, 4)
        items = self.client.get("/api/v1/telemetry?device=esp-08", headers=self.op).json()["items"]
        self.assertEqual(items, [])
        self.assertTrue(self.audit("message_rejected"))


if __name__ == "__main__":
    unittest.main()
