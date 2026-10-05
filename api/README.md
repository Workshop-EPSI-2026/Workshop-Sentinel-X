# API — responsable : Constantin (binôme sécurité : Lisa)

Point d'entrée attendu par l'image : `app/main.py` exposant `app` (FastAPI), port 8000.
Le choix de FastAPI vient de pydantic (validation stricte) ; pour passer en Node.js, seul
le `Dockerfile` change, pas le `docker-compose.yml`.

Endpoints du contrat (docs/contracts.md) : `POST /api/v1/alerts`, `GET /api/v1/telemetry?from=`,
`POST /api/v1/commands`, `GET /api/v1/health`, WebSocket `/ws`.

Variables reçues : `DATABASE_URL`, `MQTT_HOST`, `MQTT_PORT`, `MQTT_TLS`, `MQTT_CA`,
`MQTT_USER`, `MQTT_PASSWORD`, `API_KEY`.
