# API — responsable : Constantin (binôme sécurité : Lisa)

Point d'entrée attendu par l'image : `app/main.py` exposant `app` (FastAPI), port 8000, dans le conteneur `api`
(Docker Desktop sur le PC serveur). Pour passer en Node.js, seul le `Dockerfile` change, pas le `docker-compose.yml`.

Endpoints du contrat (`docs/contracts.md`) : `POST /api/v1/alerts`, `GET/PATCH /api/v1/alerts`,
`GET /api/v1/telemetry?from=`, `POST /api/v1/commands`, `GET/PUT /api/v1/config`, `GET /api/v1/score`,
`GET /api/v1/health`, WebSocket `/ws`.

Variables reçues : `DATABASE_URL`, `MQTT_HOST`, `MQTT_PORT`, `MQTT_TLS`, `MQTT_CA`, `MQTT_USER`, `MQTT_PASSWORD`,
`API_KEY`, `OPERATOR_TOKEN`, `SITE_PROFILE`, `WEBHOOK_URL`.

## Ce que l'API consomme

| Source | Contenu | Stockage (`infra/postgres/init/01-schema.sql`) |
| --- | --- | --- |
| `sentinel/+/telemetry`, `event`, `health`, `status` | Boîtiers | `telemetry`, `events`, `health`, `device_status`, `devices` |
| `sentinel/+/vision` | Caméra : personnes, zone, badges, intégrité (1 message/s) | `vision_events` **seulement quand ça change** |
| `sentinel/brain/score` | Sentinel Score et domaines | `brain_scores` + diffusion `/ws` |
| `POST /api/v1/alerts` (Brain, clé d'API) | Incidents expliqués | `alerts` (regroupement : `ON CONFLICT`, voir le README de `infra/postgres/init`) |
| `sentinel/brain/alert` | Copie MQTT des alertes | à utiliser si le POST a échoué (même format) |

Insertion idempotente : `ON CONFLICT (device_id, boot_id, seq) DO NOTHING` (un rejeu n'est jamais stocké deux fois).
Le profil de site est versionné dans `config_versions` et publié en JSON, message conservé, sur `sentinel/site/config`
(Brain et la vision le rechargent à chaud) et sur `sentinel/<id>/config` pour la partie boîtier.

## Tester sans boîtier ni caméra
```powershell
python tools\simulator.py --host localhost --port 1883 --user esp-01 --password "MDP_ESP" --scenario all --speed 10
cd ai\vision ; python -m app.main --env ..\..\infra\.env --source data\demo.mp4     # vidéo : python tools\demo_video.py
```
