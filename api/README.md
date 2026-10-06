# API — responsable : Constantin (binôme sécurité : Lisa)

FastAPI + PostgreSQL + MQTT. Elle relie les boîtiers, Sentinel Brain et la vision au dashboard, et **crée seule toute
la base de données** : au démarrage, elle attend PostgreSQL puis applique les migrations manquantes. Aucun script SQL à
lancer à la main.

```
 ESP32-S3 ──MQTT──► Mosquitto ──► ┌──────────────────────────── API (conteneur snx-api) ───────────────────────────┐
 Brain  ──score MQTT──►           │ mqtt.py  ──► service.py ──► repo.py ──► PostgreSQL (volume pg-data)             │
 Brain, Vision ──POST /alerts──►  │              │  validation (models.py), incidents, profil de site, commandes    │
                                  │              └──► hub.py ──► WebSocket /ws ──► Dashboard                        │
 Dashboard ──REST /api/v1/*────►  │ main.py (routes) ── auth.py (jeton opérateur, clé d'API)                        │
                                  └─────────────────────────────────────────────────────────────────────────────────┘
```

## Fichiers

| Fichier | Rôle |
| --- | --- |
| `app/main.py` | Application FastAPI : routes REST, WebSocket `/ws`, démarrage et arrêt |
| `app/models.py` | Modèles Pydantic du contrat (`docs/contracts.md`) : validation stricte de tout ce qui entre |
| `app/db.py` | Pool de connexions PostgreSQL et **migrations** (le schéma complet est ici) |
| `app/repo.py` | Toutes les requêtes SQL |
| `app/service.py` | Ingestion MQTT, incidents, profil de site, commandes, santé, purge, webhook |
| `app/mqtt.py` | Client MQTT (abonnements, publication des commandes et du profil) |
| `app/hub.py` | Diffusion temps réel vers les dashboards connectés |
| `app/auth.py` | Jeton opérateur et clé d'API, refus tracés |
| `app/settings.py` | Configuration lue dans l'environnement ; refuse de démarrer avec un jeton faible |
| `dev.py` | Lanceur pour un poste Windows (voir plus bas) |

## Base de données (créée par l'API)

| Table | Contenu | Conservation |
| --- | --- | --- |
| `devices` | Boîtiers connus, libellé, dernier signe de vie, état en ligne / hors ligne | — |
| `telemetry` | Mesures. `(device_id, boot_id, seq)` est unique : un tampon rejoué deux fois n'est stocké qu'une fois | 30 jours |
| `events` | PIR, effraction, seuil gaz, alarme locale, démarrage, changement de mode | 90 jours |
| `device_health` | Santé du boîtier toutes les 30 s (RSSI, mémoire, tampon…) | 7 jours |
| `scores` | Scores de Sentinel Brain toutes les 2 s | 7 jours |
| `alerts` | Incidents. Un seul incident non résolu par boîtier et par type : les répétitions incrémentent `count` | indéfinie |
| `commands` | Commandes envoyées aux boîtiers, avec l'opérateur | indéfinie |
| `config_versions` | Chaque version du profil de site ; la dernière est active | indéfinie |
| `audit_log` | Actions d'opérateur, refus d'accès, messages MQTT rejetés (signaux cyber pour Brain) | 180 jours |
| `schema_migrations` | Migrations déjà appliquées | — |

**Faire évoluer le schéma** : ajouter une migration **à la fin** de `MIGRATIONS` dans `app/db.py` (numéro suivant), sans
jamais modifier une migration déjà appliquée. Elle s'applique au prochain démarrage, dans une transaction, sous verrou
(deux API lancées ensemble ne se marchent pas dessus).

**Repartir de zéro** : `docker compose down`, puis `docker volume rm sentinel-x_pg-data` (efface les données).

## Ce que l'API garantit

- **Rien d'invalide n'entre en base** : tout message MQTT et toute requête passent par un modèle strict (types, bornes,
  champs inconnus refusés côté REST). Un message dont le `device_id` diffère du topic est rejeté et tracé.
- **Aucune mesure perdue ni doublon** : le rejeu du tampon du boîtier après une coupure est inséré avec ses horodatages
  d'origine, les doublons sont ignorés.
- **Incidents regroupés** : un même type d'incident sur un boîtier reste un seul incident tant qu'il n'est pas résolu ;
  sa gravité monte mais ne redescend jamais. L'effraction signalée par le boîtier crée un incident `sabotage` même si
  Brain est arrêté.
- **Profil de site versionné** : `PUT /api/v1/config` enregistre une nouvelle version, validée (seuils cohérents,
  bornes), puis la publie en message MQTT conservé (`sentinel/site/config` et `sentinel/<id>/config`). Elle est
  republiée à chaque reconnexion au broker.
- **Commandes** : publiées en QoS 1 avec un `id` unique et un `ts` (le boîtier ignore une commande de plus de 30 s) ;
  réponse 503 si le broker est injoignable, jamais de commande « perdue en silence ».
- **Webhook** : si `WEBHOOK_URL` ou `integrations.webhook_url` est défini, chaque nouvel incident (gravité au moins
  `warning`) est envoyé en POST JSON ; les répétitions respectent le délai `brain.cooldown_s`.

## Sécurité

| Surface | Mesure |
| --- | --- |
| Routes de l'interface | `Authorization: Bearer <OPERATOR_TOKEN>` ; refus 401 tracé dans `audit_log` |
| Routes des services | `X-API-Key: <API_KEY>` (`POST /api/v1/alerts`) |
| WebSocket | Jeton dans le **premier message**, jamais dans l'URL ; fermeture 4401 sinon |
| Démarrage | Refuse de démarrer si un jeton fait moins de 32 caractères ou contient `CHANGE_ME` |
| Comparaisons | À temps constant ; la clé des services n'ouvre pas l'interface, et inversement |
| Santé | Sans jeton : `{"status": "ok"}` seulement ; processeur, mémoire, services et boîtiers avec le jeton |
| Flux vidéo | `POST /api/v1/video/ticket` (opérateur) donne un ticket signé de 60 s ; nginx le fait vérifier (`auth_request` vers `/api/v1/video/check`, inaccessible de l'extérieur) avant d'ouvrir `/video` |
| Conteneur | Non root, système de fichiers en lecture seule, capacités retirées (`infra/docker-compose.yml`) |
| MQTT | Compte `api` aux droits minimaux (`infra/mosquitto/aclfile`) ; TLS 8884 dès mardi |

La limitation de débit est faite par nginx (`infra/nginx/nginx.conf`, réponse 429).

## Routes

Formats détaillés : `docs/contracts.md`. Documentation interactive : `https://192.168.137.1/api/docs`.

| Route | Auth | Rôle |
| --- | --- | --- |
| `GET /api/v1/health` | libre : `{"status": "ok"}` ; détail avec le jeton opérateur | Santé des services, du PC serveur et des boîtiers |
| `POST /api/v1/alerts` | clé d'API | Ingestion d'une alerte (vision, Brain) |
| `GET /api/v1/alerts?status=&domain=` | opérateur | Incidents |
| `PATCH /api/v1/alerts/{id}` | opérateur | Acquitter ou résoudre |
| `GET /api/v1/telemetry?device=&from=` | opérateur | Historique paginé (1000 mesures par page, champ `next`) |
| `GET /api/v1/score` | opérateur | Dernier score de Brain |
| `POST /api/v1/commands` | opérateur | Commande vers un boîtier (202) |
| `GET` / `PUT /api/v1/config` | opérateur | Profil de site |
| `POST /api/v1/video/ticket` | opérateur | Ticket de 60 s pour ouvrir `/video` (une balise `<img>` n'envoie pas d'en-tête) |
| `WS /ws` | opérateur | Temps réel : `telemetry`, `event`, `health`, `status`, `score`, `alert` |

## Variables d'environnement

Fournies par `infra/docker-compose.yml` depuis `infra/.env` : `DATABASE_URL`, `MQTT_HOST`, `MQTT_PORT`, `MQTT_TLS`,
`MQTT_CA`, `MQTT_USER`, `MQTT_PASSWORD`, `API_KEY`, `OPERATOR_TOKEN`, `SITE_PROFILE` (profil initial),
`WEBHOOK_URL` (optionnel), `VISION_HEALTH_URL` (par défaut la vision du PC, `http://host.docker.internal:8001/health` ;
le service vision peut y renvoyer `fps` et `latency_ms`).

## Développer

Dans Docker : `cd infra && docker compose up -d --build api` (voir `README.md` à la racine).

Sans Docker, sur un poste Windows, avec un PostgreSQL et un Mosquitto accessibles :

```powershell
cd api
$env:DATABASE_URL="postgresql://sentinel:<mdp>@localhost:5432/sentinel"
$env:MQTT_HOST="localhost"; $env:MQTT_PORT="1883"; $env:MQTT_TLS="false"
$env:MQTT_USER="api"; $env:MQTT_PASSWORD="<mdp>"
$env:API_KEY="<32 caractères minimum>"; $env:OPERATOR_TOKEN="<32 caractères minimum>"
$env:SITE_PROFILE="..\config\site.example.yml"
python dev.py        # http://127.0.0.1:8000/api/docs
```

Tests (refus sans jeton, validation, tickets vidéo, WebSocket, messages MQTT invalides ou usurpés), sur une
PostgreSQL de test jetable :

```powershell
docker run -d --name snx-pg-test -e POSTGRES_USER=sentinel -e POSTGRES_PASSWORD=testpass -e POSTGRES_DB=sentinel_test -p 55440:5432 postgres:16-alpine
$env:SENTINEL_TEST_DATABASE_URL="postgresql://sentinel:testpass@127.0.0.1:55440/sentinel_test"
pip install httpx ; python -m unittest discover -s api/tests -v      # depuis la racine du dépôt
docker rm -f snx-pg-test
```

`dev.py` est nécessaire sous Windows : la boucle d'événements par défaut d'uvicorn y est incompatible avec psycopg en
mode asynchrone. Le conteneur (Linux) lance `uvicorn app.main:app` directement.
