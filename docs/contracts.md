# Contrat d'interface — Sentinel-X v3 (PC serveur)

> Référence d'intégration. **Toute modification passe par une Pull Request et est annoncée au groupe.**
> Horodatages : secondes Unix (UTC). L'ESP32-S3 se met à l'heure sur le serveur NTP du PC (192.168.137.1).

## Réseau

| Élément | Valeur |
| --- | --- |
| Serveur | PC portable Windows 11 `sentinel-pc`, **192.168.137.1** (point d'accès mobile Windows) |
| Serveur de secours | Deuxième PC de l'équipe, même dépôt, même `.env`, mêmes certificats (même adresse en reprenant le point d'accès) |
| Boîtier | ESP32-S3 `esp-01`, adresse attribuée par le point d'accès (DHCP 192.168.137.x) |
| Caméra | Webcam USB du PC, service vision `cam-01` (sur le PC, hors Docker) |
| MQTT boîtiers et vision | 8883 TLS (1883 authentifié tant que le TLS n'est pas prêt), TLS mutuel en cible |
| MQTT services Docker | 8884 TLS, interne à Docker |
| Web | 443 HTTPS / WSS (nginx) |

Le même contrat vaut sur un serveur Linux ou un Raspberry Pi : seule l'adresse du serveur change (`secrets.h`).

## Topics MQTT

`<id>` = identifiant de l'équipement = nom du compte MQTT = CN de son certificat client (ex. `esp-01`, `cam-01`).

| Topic | Émetteur | Abonnés | QoS | Conservé | Contenu |
| --- | --- | --- | --- | --- | --- |
| `sentinel/<id>/telemetry` | Boîtier, toutes les 2 s (500 ms en suspicion) | API, Brain | 0 | non | Mesures |
| `sentinel/<id>/event` | Boîtier, immédiat | API, Brain | 1 | non | PIR, effraction, seuil gaz matériel, alarme locale, démarrage |
| `sentinel/<id>/health` | Boîtier, toutes les 30 s | API, Brain | 0 | non | Santé du boîtier |
| `sentinel/<id>/status` | Boîtier ou vision (dernière volonté : `offline`) | API, Brain | 1 | oui | `online` / `offline` |
| `sentinel/<cam>/vision` | Vision, chaque seconde et à chaque changement (5/s max) | API, Brain | 0 | non | Personnes, zone, badges, intégrité de la caméra |
| `sentinel/<id>/cmd` | API | Boîtier | 1 | non | Commandes |
| `sentinel/<id>/config` | API | Boîtier | 1 | oui | Partie « boîtier » du profil de site |
| `sentinel/site/config` | API | Brain, vision | 1 | oui | Profil de site complet (JSON) |
| `sentinel/brain/score` | Brain, à chaque mesure et chaque message vision | API | 0 | non | Scores en direct |
| `sentinel/brain/alert` | Brain, à chaque alerte | API | 1 | non | Copie MQTT de l'alerte (secours si `POST /alerts` échoue) |

## Télémétrie

| Champ | Type | Description |
| --- | --- | --- |
| `device_id` | texte | Identifiant du boîtier |
| `seq` | entier | Compteur croissant, partagé avec les événements, remis à zéro au démarrage (`boot_id` change) |
| `boot_id` | texte | Identifiant aléatoire tiré à chaque démarrage |
| `ts` | entier | Horodatage de la mesure |
| `temp_c` | nombre | Température DHT11 (°C) |
| `hum_pct` | nombre | Humidité DHT11 (%) |
| `gas_mv` | entier | Tension MQ-2 en mV, après pont diviseur, moyenne de 16 lectures |
| `gas_ratio` | nombre | `gas_mv` / ligne de base apprise (1,0 = air habituel) |
| `gas_do` | booléen | Seuil matériel du module dépassé |
| `pir` | booléen | Mouvement en cours |
| `pir_count` | entier | Déclenchements PIR sur la dernière minute |
| `mode` | texte | `learning`, `armed`, `maintenance` |
| `edge_score` | entier | Score de la garde locale, 0 à 100 |
| `replay` | booléen | Mesure renvoyée depuis le tampon après une coupure |

## Événement

`device_id`, `seq`, `boot_id`, `ts`, `type` (`pir`, `tamper`, `gas_do`, `edge_alarm`, `boot`, `mode_change`), `value`, `details` (objet).

## Santé

`device_id`, `ts`, `uptime_s`, `heap_free`, `psram_free`, `rssi`, `chip_temp_c`, `reset_reason`, `buffer_len`,
`wifi_disconnects`, `mqtt_reconnects`, `tls_errors`, `fw_version`.

## Vision (`sentinel/<cam>/vision`)

```json
{"device_id": "cam-01", "seq": 812, "boot_id": "111ae725", "ts": 1791278595.96, "fps": 10.0, "motion": true,
 "brightness": 126.0, "masked": false, "low_light": false, "frozen": false, "zone_count": 1,
 "persons": [{"track_id": 3, "in_zone": true, "dwell_s": 14.2, "badge": null, "authorized": false,
              "conf": 0.82, "box": [0.42, 0.31, 0.56, 0.91]}]}
```

| Champ | Description |
| --- | --- |
| `seq`, `boot_id` | Mêmes règles que les boîtiers : un message rejoué est détecté par Brain |
| `masked` | Image uniforme ou noire depuis 2 s (objectif couvert) |
| `low_light` | Image sombre mais texturée depuis 3 s (pièce dans le noir) : le PIR prend le relais |
| `frozen` | Image strictement identique depuis 10 s (flux remplacé par une image fixe) |
| `persons[].track_id` | Identifiant de suivi (ByteTrack), stable tant que la personne reste visible |
| `persons[].in_zone`, `dwell_s` | Pieds dans la zone interdite du profil, temps passé dans la zone |
| `persons[].badge` | Numéro du badge ArUco lu sur la personne (conservé pendant tout le suivi), `null` sinon |
| `persons[].authorized` | Indication de la vision (liste blanche seule). **Brain décide** avec la liste blanche **et** les horaires |
| `box` | Boîte normalisée 0..1 (x1, y1, x2, y2) |

## Commande (`cmd`)

`{"cmd": "alarm", "on": true}` · `{"cmd": "led", "color": "red"}` · `{"cmd": "mode", "value": "maintenance"}` ·
`{"cmd": "recalibrate"}` · `{"cmd": "reboot"}` — toujours avec `id` (unique) et `ts`. Le boîtier ignore une commande
plus vieille que 30 s ou dont l'`id` a déjà été vu.

## Alerte / incident (`POST /api/v1/alerts`, en-tête `X-API-Key`)

| Champ | Type | Description |
| --- | --- | --- |
| `device_id` | texte | Équipement concerné (`esp-01`, `cam-01`, ou `broker` pour les accès refusés) |
| `source` | texte | `brain`, `vision`, `edge` |
| `domain` | texte | `environment`, `physical`, `cyber`, `maintenance` |
| `type` | texte | voir le tableau ci-dessous |
| `severity` | texte | `info`, `warning`, `critical` |
| `score` | nombre | 0 à 100 |
| `eta_min` | nombre ou null | Minutes avant le niveau critique (prévision) |
| `ts` | entier | Horodatage de l'anomalie |
| `explanation` | texte | Phrase lisible |
| `factors` | liste | `[{"name": "gas_ratio", "value": 1.38, "contribution": 0.62}, …]` |
| `details` | objet | `retrospective` (mesures du tampon après coupure), `rx_ts`, … |

| Type | Domaine | Gravité usuelle | Quand |
| --- | --- | --- | --- |
| `intrusion_confirmed` | physical | critical | Personne sans badge dans la zone **et** PIR à moins de 5 s |
| `intrusion_suspected` | physical | warning | Vision seule, PIR seul (caméra aveugle), ou personne non badgée accompagnée d'un agent |
| `loitering` | physical | warning | Personne sans badge dans la zone depuis plus de `loitering_s` |
| `presence_authorized` | physical | info | Agent badgé dans la zone, dans ses horaires |
| `presence_to_verify` | physical | warning | Badge connu mais hors de ses horaires |
| `sabotage` | physical | critical | Boîtier ouvert, caméra masquée, ou caméra muette juste après une détection |
| `gas_leak` | environment | warning → critical | Gaz qui monte, température stable |
| `fire_risk` | environment | critical | Gaz et température qui montent ensemble |
| `thermal_drift` | environment | warning | Température qui dérive seule (panne de climatisation) |
| `unusual_pattern` | environment | info | Combinaison inhabituelle (Isolation Forest) sans dépassement d'un capteur seul |
| `jamming_suspected` | cyber | warning → critical | RSSI qui chute, puis boîtier hors ligne |
| `cyber_attack` | cyber | critical | Rejeu, horodatage falsifié, rafale d'accès MQTT refusés |
| `sensor_fault` | maintenance | warning | Capteur figé ou valeur impossible |
| `camera_degraded` | maintenance | info / warning | Image trop sombre, ou caméra hors ligne sans détection récente |

Brain envoie une alerte à l'ouverture d'un incident puis seulement quand sa gravité monte. L'API regroupe les
répétitions : un seul incident non résolu par (`device_id`, `type`) (`infra/postgres/init/01-schema.sql`).

## Score en direct (`sentinel/brain/score`)

```json
{"device_id": "esp-01", "ts": 1790002776, "score": 100, "environment": 100, "physical": 0, "cyber": 0,
 "eta_min": 3.0, "eta_by": {"gas_ratio": 3.0}, "learning": false,
 "layers": {"cusum_gas": 18, "rate_gas": 100, "cusum_temp": 0, "rate_temp": 0, "cusum_hum": 0,
            "iforest": 30, "forecast": 88, "raw": 0}}
```

`score` = maximum des trois domaines + 0,15 × la somme des deux autres (plafonné à 100). Le domaine physique d'un
boîtier inclut ce que voit la caméra. Pour une caméra (`cam-01`), `layers` donne `persons_in_zone`, `unauthorized`,
`masked`, `low_light`. `eta_by` : prévision par grandeur, `eta_min` en est le minimum. Pendant `learning`, Brain
publie des scores mais aucune alerte.

## Endpoints HTTP (via `https://192.168.137.1` ou `https://localhost` sur le PC)

| Méthode | Route | Rôle | Authentification |
| --- | --- | --- | --- |
| POST | `/api/v1/alerts` | Ingestion d'une alerte | Clé d'API (services) |
| GET | `/api/v1/alerts?status=&domain=` | Incidents | Opérateur |
| PATCH | `/api/v1/alerts/{id}` | Acquitter / résoudre | Opérateur |
| GET | `/api/v1/telemetry?from=&device=` | Historique paginé | Opérateur |
| POST | `/api/v1/commands` | Commande vers un boîtier | Opérateur |
| GET / PUT | `/api/v1/config` | Profil de site | Opérateur |
| GET | `/api/v1/score` | Scores courants | Opérateur |
| GET | `/api/v1/health` | Santé du système | Libre (supervision) |
| WS | `/ws` | Temps réel | Opérateur |
| GET | `/video` | Flux MJPEG annoté (relayé par nginx vers la vision du PC) | Opérateur |
| GET | `/vision/health` | Santé de la vision | Libre |

## Formats attendus par le dashboard

Implémentés par l'API (`api/app/`, testés de bout en bout) et attendus par le dashboard (`dashboard/src/types.ts`).
Le mode démo du dashboard simule exactement ces formats.

**Authentification opérateur** : en-tête `Authorization: Bearer <OPERATOR_TOKEN>` ; réponse 401 si le jeton est refusé.
Les services (vision, Brain) s'authentifient sur `POST /api/v1/alerts` par l'en-tête `X-API-Key: <API_KEY>`.
Exception : `/video?token=<OPERATOR_TOKEN>`, car une balise `<img>` ne peut pas envoyer d'en-tête (c'est le service
vision qui doit vérifier ce jeton : l'API n'est pas sur ce chemin).

**WebSocket `/ws`** : le client envoie d'abord `{"type": "auth", "token": "…"}` (jamais de jeton dans l'URL, qui
finirait dans les journaux nginx). L'API répond `{"type": "ready"}`, ou ferme avec le code 4401. Elle pousse ensuite
`{"type": <type>, "data": {…}}` :

| `type` | `data` |
| --- | --- |
| `telemetry`, `event`, `health`, `status` | Message MQTT du boîtier, tel quel |
| `score` | `{ts, global, environment, physical, cyber}` (contenu de `sentinel/brain/score`, scores 0 à 100) |
| `alert` | Incident complet, à chaque création ou mise à jour |

**Incident** (réponse de `GET /api/v1/alerts`, élément de liste) : les champs de l'alerte ci-dessus, plus `id` (entier),
`status` (`open`, `acknowledged`, `resolved`) et `count` (répétitions regroupées).

| Route | Corps envoyé | Réponse |
| --- | --- | --- |
| `POST /api/v1/alerts` | Alerte du contrat (clé d'API) | 201 avec l'incident ; regroupé avec l'incident non résolu du même type sur le même boîtier (`count` + 1, gravité jamais abaissée) |
| `GET /api/v1/alerts?status=&domain=` | — | Liste d'incidents, du plus récent au plus ancien |
| `PATCH /api/v1/alerts/{id}` | `{"status": "acknowledged"}` ou `"resolved"` | Incident mis à jour |
| `GET /api/v1/telemetry?device=&from=` | — | `{"items": [télémétrie…], "next": <from suivant> ou null}`, trié par `ts` croissant |
| `POST /api/v1/commands` | `{"device_id": "esp-01", "cmd": "alarm", "on": true}` (champs de la commande : `on` pour `alarm`, `color` pour `led`, `value` pour `mode`) | 202 avec la commande publiée, `id` et `ts` ajoutés par l'API ; 503 si le broker est injoignable |
| `GET /api/v1/config` | — | `{"version", "updated_at", "profile"}` ; `profile` = profil de site en JSON (structure de `config/site.example.yml`) |
| `PUT /api/v1/config` | `{"profile": {…}}` | Même réponse que `GET`, version incrémentée |
| `GET /api/v1/score` | — | Dernier score, ou `null` |
| `GET /api/v1/health` | — | `{"ts", "server": {"cpu_pct", "mem_pct", "uptime_s"}, "services": [{"name", "ok", "detail"}], "vision": {"fps", "latency_ms"} ou null, "devices": [santé…]}` |

## Points ouverts (docs/coachs.md)
- Format imposé de `POST /api/v1/alerts` par les coachs : à confirmer. Si imposé, ce contrat s'y aligne.
