"""Accès PostgreSQL : petit pool de connexions asynchrones et création du schéma par migrations.

La base est entièrement créée par l'API : au démarrage, chaque migration absente de `schema_migrations` est appliquée
dans une transaction. Pour faire évoluer le schéma, AJOUTER une migration en fin de liste, ne jamais modifier une
migration déjà appliquée.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import psycopg
from psycopg.rows import dict_row

log = logging.getLogger("sentinel.db")

MIGRATIONS: list[tuple[int, str, str]] = [
    (1, "schéma initial", """
        CREATE TABLE devices (
            device_id   text PRIMARY KEY,
            label       text,
            first_seen  timestamptz NOT NULL DEFAULT now(),
            last_seen   timestamptz,
            status      text NOT NULL DEFAULT 'unknown' CHECK (status IN ('online', 'offline', 'unknown')),
            status_ts   timestamptz
        );

        -- Mesures du boîtier : (device_id, boot_id, seq) identifie une mesure, un rejeu du tampon PSRAM est ignoré
        CREATE TABLE telemetry (
            id          bigserial PRIMARY KEY,
            device_id   text NOT NULL REFERENCES devices(device_id),
            ts          timestamptz NOT NULL,
            seq         integer NOT NULL,
            boot_id     text NOT NULL,
            temp_c      real,
            hum_pct     real,
            gas_mv      integer,
            gas_ratio   real,
            gas_do      boolean,
            pir         boolean,
            pir_count   integer,
            mode        text,
            edge_score  integer,
            replay      boolean NOT NULL DEFAULT false,
            received_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (device_id, boot_id, seq)
        );
        CREATE INDEX telemetry_device_ts ON telemetry (device_id, ts);

        CREATE TABLE events (
            id          bigserial PRIMARY KEY,
            device_id   text NOT NULL REFERENCES devices(device_id),
            ts          timestamptz NOT NULL,
            seq         integer NOT NULL,
            boot_id     text NOT NULL,
            type        text NOT NULL,
            value       jsonb,
            details     jsonb NOT NULL DEFAULT '{}',
            received_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (device_id, boot_id, seq)
        );
        CREATE INDEX events_device_ts ON events (device_id, ts);

        CREATE TABLE device_health (
            id          bigserial PRIMARY KEY,
            device_id   text NOT NULL REFERENCES devices(device_id),
            ts          timestamptz NOT NULL,
            rssi        integer,
            buffer_len  integer,
            payload     jsonb NOT NULL
        );
        CREATE INDEX device_health_device_ts ON device_health (device_id, ts);

        -- Scores de Sentinel Brain (toutes les 2 s)
        CREATE TABLE scores (
            ts          timestamptz PRIMARY KEY,
            global      real NOT NULL,
            environment real NOT NULL,
            physical    real NOT NULL,
            cyber       real NOT NULL
        );

        -- Incidents : les répétitions d'un même type sur un même boîtier sont regroupées (count) tant qu'il n'est pas résolu
        CREATE TABLE alerts (
            id              serial PRIMARY KEY,
            device_id       text NOT NULL,
            source          text NOT NULL CHECK (source IN ('vision', 'brain', 'edge')),
            domain          text NOT NULL CHECK (domain IN ('environment', 'physical', 'cyber', 'maintenance')),
            type            text NOT NULL,
            severity        text NOT NULL CHECK (severity IN ('info', 'warning', 'critical')),
            status          text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'acknowledged', 'resolved')),
            score           real NOT NULL,
            eta_min         real,
            explanation     text NOT NULL,
            factors         jsonb NOT NULL DEFAULT '[]',
            details         jsonb NOT NULL DEFAULT '{}',
            count           integer NOT NULL DEFAULT 1,
            first_ts        timestamptz NOT NULL,
            ts              timestamptz NOT NULL,
            notified_at     timestamptz,
            acknowledged_at timestamptz,
            resolved_at     timestamptz
        );
        CREATE INDEX alerts_status ON alerts (status, ts DESC);
        -- Au plus un incident non résolu par boîtier et par type (regroupement garanti par la base)
        CREATE UNIQUE INDEX alerts_active_unique ON alerts (device_id, type) WHERE status <> 'resolved';

        CREATE TABLE commands (
            id          uuid PRIMARY KEY,
            device_id   text NOT NULL,
            payload     jsonb NOT NULL,
            created_at  timestamptz NOT NULL DEFAULT now(),
            actor       text NOT NULL
        );

        -- Profil de site versionné : la dernière version est la configuration active
        CREATE TABLE config_versions (
            version     serial PRIMARY KEY,
            profile     jsonb NOT NULL,
            created_at  timestamptz NOT NULL DEFAULT now(),
            actor       text NOT NULL
        );

        -- Traçabilité de chaque action d'opérateur et de chaque refus d'accès (signal cyber)
        CREATE TABLE audit_log (
            id          bigserial PRIMARY KEY,
            ts          timestamptz NOT NULL DEFAULT now(),
            actor       text NOT NULL,
            action      text NOT NULL,
            target      text,
            details     jsonb NOT NULL DEFAULT '{}'
        );
        CREATE INDEX audit_log_ts ON audit_log (ts);
    """),
]


class Database:
    """Pool minimal : quelques connexions en autocommit, recréées si PostgreSQL redémarre."""

    def __init__(self, url: str, size: int = 5) -> None:
        self.url = url
        self.size = size
        self._idle: asyncio.Queue[psycopg.AsyncConnection] = asyncio.Queue()
        self._created = 0
        self._lock = asyncio.Lock()

    async def _new(self) -> psycopg.AsyncConnection:
        return await psycopg.AsyncConnection.connect(self.url, autocommit=True, row_factory=dict_row)

    @asynccontextmanager
    async def conn(self) -> AsyncIterator[psycopg.AsyncConnection]:
        async with self._lock:
            if self._idle.empty() and self._created < self.size:
                self._created += 1
                try:
                    self._idle.put_nowait(await self._new())
                except Exception:
                    self._created -= 1
                    raise
        conn = await self._idle.get()
        try:
            if conn.closed or conn.broken:
                conn = await self._new()
            yield conn
        except psycopg.OperationalError:
            await conn.close()  # connexion perdue : remplacée au prochain emprunt
            raise
        finally:
            self._idle.put_nowait(conn)

    async def connect(self, attempts: int = 30) -> None:
        """Attend PostgreSQL (démarrage de la stack) puis applique les migrations."""
        for i in range(1, attempts + 1):
            try:
                async with self.conn() as c:
                    await c.execute("SELECT 1")
                break
            except psycopg.OperationalError as e:
                if i == attempts:
                    raise
                log.warning("PostgreSQL indisponible (%s), nouvel essai dans 2 s", e)
                await asyncio.sleep(2)
        await self.migrate()

    async def migrate(self) -> None:
        async with self.conn() as c:
            await c.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                " version integer PRIMARY KEY, name text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())"
            )
            # Verrou applicatif : deux API démarrées en même temps n'appliquent pas deux fois la même migration
            await c.execute("SELECT pg_advisory_lock(424242)")
            try:
                rows = await (await c.execute("SELECT version FROM schema_migrations")).fetchall()
                done = {r["version"] for r in rows}
                for version, name, sql in MIGRATIONS:
                    if version in done:
                        continue
                    async with c.transaction():
                        await c.execute(sql)
                        await c.execute("INSERT INTO schema_migrations (version, name) VALUES (%s, %s)", (version, name))
                    log.info("Migration %s appliquée : %s", version, name)
            finally:
                await c.execute("SELECT pg_advisory_unlock(424242)")

    async def ping(self) -> bool:
        try:
            async with self.conn() as c:
                await c.execute("SELECT 1")
            return True
        except Exception:
            return False

    async def close(self) -> None:
        while not self._idle.empty():
            await self._idle.get_nowait().close()
