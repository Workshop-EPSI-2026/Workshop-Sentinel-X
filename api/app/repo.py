"""Requêtes SQL. Horodatages : timestamptz en base, secondes Unix dans le contrat (conversion ici uniquement)."""
from __future__ import annotations

import uuid
from typing import Any

from psycopg.types.json import Jsonb

from .db import Database
from .models import AlertIn, DeviceEvent, DeviceHealth, Scores, Telemetry

SEVERITY_RANK = {"info": 0, "warning": 1, "critical": 2}

ALERT_COLUMNS = """
    id, status, count, device_id, source, domain, type, severity, score, eta_min,
    extract(epoch FROM ts)::float8 AS ts, explanation, factors, details
"""


class Repo:
    def __init__(self, db: Database) -> None:
        self.db = db

    # ------------------------------------------------------------------------------------------------ boîtiers
    async def touch_device(self, device_id: str, ts: float) -> None:
        async with self.db.conn() as c:
            await c.execute(
                """INSERT INTO devices (device_id, last_seen) VALUES (%s, to_timestamp(%s))
                   ON CONFLICT (device_id) DO UPDATE SET last_seen = GREATEST(devices.last_seen, EXCLUDED.last_seen)""",
                (device_id, ts),
            )

    async def set_status(self, device_id: str, status: str, ts: float) -> None:
        async with self.db.conn() as c:
            await c.execute(
                """INSERT INTO devices (device_id, status, status_ts) VALUES (%s, %s, to_timestamp(%s))
                   ON CONFLICT (device_id) DO UPDATE SET status = EXCLUDED.status, status_ts = EXCLUDED.status_ts""",
                (device_id, status, ts),
            )

    async def sync_device_labels(self, devices: dict[str, Any]) -> None:
        async with self.db.conn() as c:
            for device_id, profile in devices.items():
                await c.execute(
                    """INSERT INTO devices (device_id, label) VALUES (%s, %s)
                       ON CONFLICT (device_id) DO UPDATE SET label = EXCLUDED.label""",
                    (device_id, profile.get("label")),
                )

    async def device_statuses(self) -> list[dict[str, Any]]:
        async with self.db.conn() as c:
            cur = await c.execute(
                """SELECT device_id, status, extract(epoch FROM status_ts)::float8 AS ts FROM devices
                   WHERE status <> 'unknown'"""
            )
            return await cur.fetchall()

    # ---------------------------------------------------------------------------------------- mesures et santé
    async def insert_telemetry(self, t: Telemetry) -> bool:
        """False si la mesure est déjà connue (rejeu du tampon déjà reçu)."""
        await self.touch_device(t.device_id, t.ts)
        async with self.db.conn() as c:
            cur = await c.execute(
                """INSERT INTO telemetry (device_id, ts, seq, boot_id, temp_c, hum_pct, gas_mv, gas_ratio, gas_do, pir,
                                          pir_count, mode, edge_score, replay)
                   VALUES (%s, to_timestamp(%s), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (device_id, boot_id, seq) DO NOTHING""",
                (t.device_id, t.ts, t.seq, t.boot_id, t.temp_c, t.hum_pct, t.gas_mv, t.gas_ratio, t.gas_do, t.pir,
                 t.pir_count, t.mode, t.edge_score, t.replay),
            )
            return cur.rowcount == 1

    async def insert_event(self, e: DeviceEvent) -> bool:
        await self.touch_device(e.device_id, e.ts)
        async with self.db.conn() as c:
            cur = await c.execute(
                """INSERT INTO events (device_id, ts, seq, boot_id, type, value, details)
                   VALUES (%s, to_timestamp(%s), %s, %s, %s, %s, %s)
                   ON CONFLICT (device_id, boot_id, seq) DO NOTHING""",
                (e.device_id, e.ts, e.seq, e.boot_id, e.type, Jsonb(e.value), Jsonb(e.details)),
            )
            return cur.rowcount == 1

    async def insert_health(self, h: DeviceHealth) -> None:
        await self.touch_device(h.device_id, h.ts)
        async with self.db.conn() as c:
            await c.execute(
                """INSERT INTO device_health (device_id, ts, rssi, buffer_len, payload)
                   VALUES (%s, to_timestamp(%s), %s, %s, %s)""",
                (h.device_id, h.ts, h.rssi, h.buffer_len, Jsonb(h.model_dump())),
            )

    async def latest_health(self) -> list[dict[str, Any]]:
        async with self.db.conn() as c:
            cur = await c.execute(
                "SELECT DISTINCT ON (device_id) payload FROM device_health ORDER BY device_id, ts DESC"
            )
            return [r["payload"] for r in await cur.fetchall()]

    async def telemetry_page(self, device_id: str, from_ts: float, limit: int) -> tuple[list[dict[str, Any]], float | None]:
        async with self.db.conn() as c:
            cur = await c.execute(
                """SELECT device_id, seq, boot_id, extract(epoch FROM ts)::float8 AS ts, temp_c, hum_pct, gas_mv,
                          gas_ratio, gas_do, pir, pir_count, mode, edge_score, replay
                   FROM telemetry WHERE device_id = %s AND ts >= to_timestamp(%s)
                   ORDER BY ts, seq LIMIT %s""",
                (device_id, from_ts, limit),
            )
            items = await cur.fetchall()
        # Page pleine : la suivante commence juste après la dernière mesure renvoyée
        nxt = items[-1]["ts"] + 0.0005 if len(items) == limit else None
        return items, nxt

    async def insert_score(self, s: Scores) -> None:
        async with self.db.conn() as c:
            await c.execute(
                """INSERT INTO scores (ts, global, environment, physical, cyber)
                   VALUES (to_timestamp(%s), %s, %s, %s, %s) ON CONFLICT (ts) DO NOTHING""",
                (s.ts, s.global_, s.environment, s.physical, s.cyber),
            )

    async def latest_score(self) -> dict[str, Any] | None:
        async with self.db.conn() as c:
            cur = await c.execute(
                """SELECT extract(epoch FROM ts)::float8 AS ts, global, environment, physical, cyber
                   FROM scores ORDER BY ts DESC LIMIT 1"""
            )
            return await cur.fetchone()

    # ------------------------------------------------------------------------------------------------ incidents
    async def upsert_alert(self, a: AlertIn) -> tuple[dict[str, Any], bool]:
        """Crée l'incident, ou regroupe avec l'incident non résolu du même type sur ce boîtier.

        Renvoie (incident, nouveau). La gravité ne redescend jamais tant que l'incident est ouvert (escalade).
        """
        async with self.db.conn() as c, c.transaction():
            cur = await c.execute(
                f"""UPDATE alerts SET
                        count = count + 1, ts = GREATEST(ts, to_timestamp(%(ts)s)), score = %(score)s,
                        eta_min = %(eta_min)s, explanation = %(explanation)s, factors = %(factors)s,
                        details = %(details)s, source = %(source)s,
                        severity = CASE WHEN %(rank)s > (CASE severity WHEN 'critical' THEN 2 WHEN 'warning' THEN 1 ELSE 0 END)
                                        THEN %(severity)s ELSE severity END
                    WHERE device_id = %(device_id)s AND type = %(type)s AND status <> 'resolved'
                    RETURNING {ALERT_COLUMNS}""",
                self._alert_params(a),
            )
            row = await cur.fetchone()
            if row:
                return row, False
            cur = await c.execute(
                f"""INSERT INTO alerts (device_id, source, domain, type, severity, score, eta_min, explanation, factors,
                                        details, first_ts, ts)
                    VALUES (%(device_id)s, %(source)s, %(domain)s, %(type)s, %(severity)s, %(score)s, %(eta_min)s,
                            %(explanation)s, %(factors)s, %(details)s, to_timestamp(%(ts)s), to_timestamp(%(ts)s))
                    RETURNING {ALERT_COLUMNS}""",
                self._alert_params(a),
            )
            return await cur.fetchone(), True

    @staticmethod
    def _alert_params(a: AlertIn) -> dict[str, Any]:
        return {
            **a.model_dump(exclude={"factors", "details"}),
            "factors": Jsonb([f.model_dump() for f in a.factors]),
            "details": Jsonb(a.details),
            "rank": SEVERITY_RANK[a.severity],
        }

    async def mark_notified(self, alert_id: int, cooldown_s: int) -> bool:
        """True si la notification sortante (webhook) est due : délai minimal entre deux notifications respecté."""
        async with self.db.conn() as c:
            cur = await c.execute(
                """UPDATE alerts SET notified_at = now() WHERE id = %s
                   AND (notified_at IS NULL OR notified_at < now() - make_interval(secs => %s))""",
                (alert_id, cooldown_s),
            )
            return cur.rowcount == 1

    async def list_alerts(self, status: str | None, domain: str | None, limit: int = 500) -> list[dict[str, Any]]:
        async with self.db.conn() as c:
            cur = await c.execute(
                f"""SELECT {ALERT_COLUMNS} FROM alerts
                    WHERE (%(status)s::text IS NULL OR status = %(status)s)
                      AND (%(domain)s::text IS NULL OR domain = %(domain)s)
                    ORDER BY ts DESC LIMIT %(limit)s""",
                {"status": status, "domain": domain, "limit": limit},
            )
            return await cur.fetchall()

    async def update_alert_status(self, alert_id: int, status: str) -> dict[str, Any] | None:
        column = "acknowledged_at" if status == "acknowledged" else "resolved_at"
        async with self.db.conn() as c:
            cur = await c.execute(
                f"""UPDATE alerts SET status = %s, {column} = now()
                    WHERE id = %s AND status <> 'resolved' RETURNING {ALERT_COLUMNS}""",
                (status, alert_id),
            )
            return await cur.fetchone()

    # ------------------------------------------------------------------------------- commandes, configuration, audit
    async def insert_command(self, device_id: str, payload: dict[str, Any], actor: str) -> None:
        async with self.db.conn() as c:
            await c.execute(
                "INSERT INTO commands (id, device_id, payload, actor) VALUES (%s, %s, %s, %s)",
                (uuid.UUID(payload["id"]), device_id, Jsonb(payload), actor),
            )

    async def latest_config(self) -> dict[str, Any] | None:
        async with self.db.conn() as c:
            cur = await c.execute(
                """SELECT version, extract(epoch FROM created_at)::float8 AS updated_at, profile
                   FROM config_versions ORDER BY version DESC LIMIT 1"""
            )
            return await cur.fetchone()

    async def insert_config(self, profile: dict[str, Any], actor: str) -> dict[str, Any]:
        async with self.db.conn() as c:
            cur = await c.execute(
                """INSERT INTO config_versions (profile, actor) VALUES (%s, %s)
                   RETURNING version, extract(epoch FROM created_at)::float8 AS updated_at, profile""",
                (Jsonb(profile), actor),
            )
            return await cur.fetchone()

    async def audit(self, actor: str, action: str, target: str | None = None, details: dict[str, Any] | None = None) -> None:
        async with self.db.conn() as c:
            await c.execute(
                "INSERT INTO audit_log (actor, action, target, details) VALUES (%s, %s, %s, %s)",
                (actor, action, target, Jsonb(details or {})),
            )
