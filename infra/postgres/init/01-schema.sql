-- =============================================================================
--  Sentinel-X — schéma PostgreSQL 16 (tâche c5 : Jeffrick avec Constantin)
--  Exécuté UNE seule fois, au premier démarrage du conteneur postgres (volume pg-data vide).
--  Le conteneur l'exécute avec l'utilisateur POSTGRES_USER, propriétaire de toutes les tables.
--
--  Principes
--   - On garde le message tel qu'il est arrivé : seq, boot_id, replay, heure de mesure (ts) ET heure de
--     réception (received_at). Sentinel Brain peut ainsi rejouer l'historique en passant ses contrôles
--     d'intégrité (rejeu, trous de séquence), et la calibration se refait sur des données réelles.
--   - Idempotent : (device_id, boot_id, seq) est unique ; l'API insère avec ON CONFLICT DO NOTHING.
--     Un message rejoué par un attaquant n'est donc jamais stocké deux fois (Brain, lui, le signale).
--   - Horodatages en timestamptz (UTC en base, affichés en Europe/Paris).
-- =============================================================================

SET client_min_messages = warning;
SET timezone = 'UTC';

-- ----------------------------------------------------------------- équipements
CREATE TABLE devices (
    device_id     text PRIMARY KEY CHECK (device_id ~ '^[a-z0-9][a-z0-9-]{1,31}$'),
    kind          text NOT NULL DEFAULT 'edge' CHECK (kind IN ('edge', 'camera')),
    label         text,
    status        text NOT NULL DEFAULT 'unknown' CHECK (status IN ('online', 'offline', 'unknown')),
    boot_id       text,
    fw_version    text,
    first_seen    timestamptz NOT NULL DEFAULT now(),
    last_seen     timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE devices IS 'Boîtiers ESP32-S3 (edge) et caméras (camera). Créés à la première réception.';

-- ----------------------------------------------------------------- télémétrie
CREATE TABLE telemetry (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    device_id     text NOT NULL REFERENCES devices (device_id),
    boot_id       text NOT NULL,
    seq           integer NOT NULL CHECK (seq >= 0),
    ts            timestamptz NOT NULL,                   -- heure de la mesure (boîtier)
    received_at   timestamptz NOT NULL DEFAULT now(),     -- heure de réception (serveur)
    temp_c        real CHECK (temp_c BETWEEN -40 AND 125),
    hum_pct       real CHECK (hum_pct BETWEEN 0 AND 100),
    gas_mv        integer CHECK (gas_mv BETWEEN 0 AND 5000),
    gas_ratio     real CHECK (gas_ratio >= 0),
    gas_do        boolean,
    pir           boolean,
    pir_count     smallint CHECK (pir_count >= 0),
    mode          text CHECK (mode IN ('learning', 'armed', 'maintenance')),
    edge_score    smallint CHECK (edge_score BETWEEN 0 AND 100),
    replay        boolean NOT NULL DEFAULT false,         -- renvoyée depuis le tampon après une coupure
    UNIQUE (device_id, boot_id, seq)
);
CREATE INDEX telemetry_device_ts ON telemetry (device_id, ts DESC);
CREATE INDEX telemetry_ts_brin   ON telemetry USING brin (ts);
COMMENT ON COLUMN telemetry.replay IS 'true = mesure ancienne renvoyée par le boîtier après une coupure réseau (légitime)';

-- ----------------------------------------------------------------- événements
CREATE TABLE events (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    device_id     text NOT NULL REFERENCES devices (device_id),
    boot_id       text NOT NULL,
    seq           integer NOT NULL CHECK (seq >= 0),
    ts            timestamptz NOT NULL,
    received_at   timestamptz NOT NULL DEFAULT now(),
    type          text NOT NULL CHECK (type IN ('pir', 'tamper', 'gas_do', 'edge_alarm', 'boot', 'mode_change')),
    value         jsonb,
    details       jsonb NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (device_id, boot_id, seq)
);
CREATE INDEX events_device_ts ON events (device_id, ts DESC);
CREATE INDEX events_type_ts   ON events (type, ts DESC);

-- ----------------------------------------------------------------- santé des boîtiers
CREATE TABLE health (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    device_id        text NOT NULL REFERENCES devices (device_id),
    ts               timestamptz NOT NULL,
    received_at      timestamptz NOT NULL DEFAULT now(),
    uptime_s         integer,
    heap_free        integer,
    psram_free       integer,
    rssi             smallint,
    chip_temp_c      real,
    reset_reason     text,
    buffer_len       integer,
    wifi_disconnects integer,
    mqtt_reconnects  integer,
    tls_errors       integer,
    fw_version       text
);
CREATE INDEX health_device_ts ON health (device_id, ts DESC);

-- ----------------------------------------------------------------- statut en ligne / hors ligne
CREATE TABLE device_status (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    device_id     text NOT NULL REFERENCES devices (device_id),
    status        text NOT NULL CHECK (status IN ('online', 'offline')),
    received_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX device_status_device ON device_status (device_id, received_at DESC);

-- ----------------------------------------------------------------- vision
-- Un résumé par seconde est publié sur sentinel/<cam>/vision ; l'API ne stocke que les changements
-- (personnes, zone, intégrité) pour ne pas remplir la base d'images vides.
CREATE TABLE vision_events (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    device_id     text NOT NULL REFERENCES devices (device_id),
    boot_id       text NOT NULL,
    seq           integer NOT NULL,
    ts            timestamptz NOT NULL,
    received_at   timestamptz NOT NULL DEFAULT now(),
    persons       smallint NOT NULL DEFAULT 0,
    in_zone       smallint NOT NULL DEFAULT 0,
    unauthorized  smallint NOT NULL DEFAULT 0,
    motion        boolean,
    masked        boolean,
    low_light     boolean,
    fps           real,
    payload       jsonb NOT NULL,                          -- message complet (personnes, badges, temps de présence)
    UNIQUE (device_id, boot_id, seq)
);
CREATE INDEX vision_events_device_ts ON vision_events (device_id, ts DESC);

-- ----------------------------------------------------------------- scores de Sentinel Brain
CREATE TABLE brain_scores (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    device_id     text NOT NULL,
    ts            timestamptz NOT NULL,
    score         smallint NOT NULL CHECK (score BETWEEN 0 AND 100),
    environment   smallint NOT NULL CHECK (environment BETWEEN 0 AND 100),
    physical      smallint NOT NULL CHECK (physical BETWEEN 0 AND 100),
    cyber         smallint NOT NULL CHECK (cyber BETWEEN 0 AND 100),
    eta_min       real,
    layers        jsonb
);
CREATE INDEX brain_scores_device_ts ON brain_scores (device_id, ts DESC);

-- ----------------------------------------------------------------- incidents (alertes)
CREATE TABLE alerts (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    device_id     text NOT NULL,
    source        text NOT NULL CHECK (source IN ('brain', 'vision', 'edge')),
    domain        text NOT NULL CHECK (domain IN ('environment', 'physical', 'cyber', 'maintenance')),
    type          text NOT NULL CHECK (type IN (
                    'intrusion_confirmed', 'intrusion_suspected', 'loitering', 'presence_authorized',
                    'presence_to_verify', 'sabotage', 'fire_risk', 'gas_leak', 'thermal_drift',
                    'unusual_pattern', 'jamming_suspected', 'cyber_attack', 'sensor_fault',
                    'camera_degraded')),
    severity      text NOT NULL CHECK (severity IN ('info', 'warning', 'critical')),
    score         smallint NOT NULL CHECK (score BETWEEN 0 AND 100),
    eta_min       real,
    ts            timestamptz NOT NULL,                    -- instant de l'anomalie
    received_at   timestamptz NOT NULL DEFAULT now(),
    explanation   text NOT NULL,
    factors       jsonb NOT NULL DEFAULT '[]'::jsonb,
    details       jsonb NOT NULL DEFAULT '{}'::jsonb,
    -- cycle de vie : ouvert -> acquitté -> résolu ; les répétitions d'un incident ouvert sont regroupées
    status        text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'acknowledged', 'resolved')),
    occurrences   integer NOT NULL DEFAULT 1,
    last_seen_at  timestamptz NOT NULL DEFAULT now(),
    acknowledged_by text,
    acknowledged_at timestamptz,
    resolved_by   text,
    resolved_at   timestamptz
);
CREATE INDEX alerts_status_severity ON alerts (status, severity, ts DESC);
CREATE INDEX alerts_device_ts       ON alerts (device_id, ts DESC);
-- Un seul incident non résolu par (boîtier, type) : l'API fait un INSERT ... ON CONFLICT pour regrouper
-- (occurrences + 1, gravité et score maximum, explication la plus récente).
CREATE UNIQUE INDEX alerts_one_active ON alerts (device_id, type) WHERE status <> 'resolved';

-- ----------------------------------------------------------------- commandes vers les boîtiers
CREATE TABLE commands (
    id            text PRIMARY KEY,                        -- identifiant unique envoyé au boîtier (anti-rejeu)
    device_id     text NOT NULL,
    cmd           text NOT NULL CHECK (cmd IN ('alarm', 'led', 'mode', 'recalibrate', 'reboot')),
    payload       jsonb NOT NULL,
    issued_by     text NOT NULL,
    issued_at     timestamptz NOT NULL DEFAULT now(),
    published     boolean NOT NULL DEFAULT false
);
CREATE INDEX commands_device ON commands (device_id, issued_at DESC);

-- ----------------------------------------------------------------- profil de site versionné
CREATE TABLE config_versions (
    version       integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    profile       jsonb NOT NULL,
    created_by    text NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    comment       text
);

-- ----------------------------------------------------------------- journal des actions d'opérateur
CREATE TABLE audit_log (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    at            timestamptz NOT NULL DEFAULT now(),
    actor         text NOT NULL,
    action        text NOT NULL,                           -- ex. alert.ack, config.update, command.send
    target        text,
    details       jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX audit_log_at ON audit_log (at DESC);

-- ----------------------------------------------------------------- vues utiles
-- Dernière mesure de chaque boîtier (dashboard, page Système)
CREATE VIEW v_latest_telemetry AS
SELECT DISTINCT ON (device_id) *
FROM telemetry
ORDER BY device_id, ts DESC;

-- Incidents à traiter, les plus graves d'abord
CREATE VIEW v_open_alerts AS
SELECT *
FROM alerts
WHERE status <> 'resolved'
ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END, ts DESC;

-- Export d'entraînement : au format du simulateur (ts en secondes), pour relancer la calibration du notebook
--   \copy (SELECT * FROM v_training_telemetry WHERE ts > now() - interval '6 hours') TO 'reel.csv' CSV HEADER
CREATE VIEW v_training_telemetry AS
SELECT device_id, seq, boot_id, extract(epoch FROM ts)::bigint AS ts, temp_c, hum_pct, gas_mv, gas_ratio, gas_do,
       pir, pir_count, mode, edge_score, replay, extract(epoch FROM received_at) AS received_at
FROM telemetry
ORDER BY device_id, ts;

-- ----------------------------------------------------------------- rétention
-- Purge des données brutes plus vieilles que n jours (incidents, configuration et journal conservés).
CREATE FUNCTION purge_raw_data(days integer DEFAULT 30) RETURNS void
LANGUAGE sql AS $$
    DELETE FROM telemetry     WHERE ts < now() - make_interval(days => days);
    DELETE FROM health        WHERE ts < now() - make_interval(days => days);
    DELETE FROM vision_events WHERE ts < now() - make_interval(days => days);
    DELETE FROM brain_scores  WHERE ts < now() - make_interval(days => days);
$$;
