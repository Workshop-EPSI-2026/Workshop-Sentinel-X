# Base de données PostgreSQL 16

`01-schema.sql` (tâche c5) est exécuté **une seule fois**, au premier démarrage du conteneur (volume `pg-data` vide).

| Table | Contenu | Écrite par |
| --- | --- | --- |
| `devices` | Boîtiers (`edge`) et caméras (`camera`), statut, dernière réception | API |
| `telemetry` | Mesures, **avec** `seq`, `boot_id`, `replay`, `ts` (mesure) et `received_at` (réception) | API |
| `events`, `health`, `device_status` | Événements, santé toutes les 30 s, passages en ligne / hors ligne | API |
| `vision_events` | Changements vus par la caméra (personnes, zone, badges, intégrité) | API |
| `brain_scores` | Sentinel Score et scores par domaine | API (depuis `sentinel/brain/score`) |
| `alerts` | Incidents, cycle de vie ouvert → acquitté → résolu, regroupement des répétitions | API |
| `commands`, `config_versions`, `audit_log` | Commandes, profil de site versionné, actions des opérateurs | API |

Règles d'insertion pour l'API (Constantin) :

```sql
-- mesure : idempotente, un rejeu malveillant n'est jamais stocké deux fois
INSERT INTO telemetry (...) VALUES (...) ON CONFLICT (device_id, boot_id, seq) DO NOTHING;

-- alerte : un seul incident non résolu par (boîtier, type), les répétitions sont regroupées
INSERT INTO alerts (...) VALUES (...)
ON CONFLICT (device_id, type) WHERE status <> 'resolved' DO UPDATE
SET occurrences = alerts.occurrences + 1, last_seen_at = now(),
    severity = CASE WHEN EXCLUDED.severity = 'critical' OR alerts.severity = 'critical' THEN 'critical'
                    WHEN EXCLUDED.severity = 'warning'  OR alerts.severity = 'warning'  THEN 'warning'
                    ELSE 'info' END,
    score = greatest(alerts.score, EXCLUDED.score), explanation = EXCLUDED.explanation,
    factors = EXCLUDED.factors, eta_min = EXCLUDED.eta_min;
```

Export de données réelles pour recalibrer Sentinel Brain (notebook `ai/anomaly/notebooks/01-prototype.ipynb`) :

```powershell
docker exec -it snx-postgres psql -U sentinel -d sentinel -c "\copy (SELECT * FROM v_training_telemetry WHERE ts > now() - interval '6 hours') TO STDOUT CSV HEADER" > ai\anomaly\data\reel.csv
```

Rejouer l'initialisation (**efface toutes les données**, exporter avant) :

```powershell
cd infra
docker compose down
docker volume rm sentinel-x_pg-data
docker compose up -d
```
