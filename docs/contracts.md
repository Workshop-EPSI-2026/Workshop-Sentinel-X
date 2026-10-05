# Contrat d'interface — Sentinel-X

> Document de référence pour l'intégration (tâche g5 : Constantin, Momo, Jeffrick).
> **Toute modification est annoncée au groupe et passe par une Pull Request.**

## Réseau

| Élément | Valeur |
|---|---|
| Nom d'hôte du serveur | `sentinel-pi` |
| IP du serveur (Pi, point d'accès et passerelle) | `192.168.10.1` (à confirmer avec la plage donnée par les coachs) |
| MQTT | `8883` MQTTS (lundi : `1883` authentifié, fermé dès le passage en TLS) |
| Web | `443` HTTPS / WSS |
| Administration | `22` SSH par clé, depuis le sous-réseau admin uniquement |

## Topics MQTT

| Topic | Émetteur | Abonnés | Contenu |
|---|---|---|---|
| `sentinel/<id>/telemetry` | ESP8266 (toutes les 2 s) | API, anomalies | Mesures |
| `sentinel/<id>/state` | ESP8266 (sur changement) | API | PIR, seuil de sécurité matériel, état |
| `sentinel/<id>/cmd` | API | ESP8266 | Commandes buzzer et LEDs |

`<id>` = `device_id` = nom du compte MQTT du boîtier (ex. `esp-01`). Les droits sont dans `infra/mosquitto/aclfile`.

## Message de télémétrie

| Champ | Type | Description |
|---|---|---|
| `device_id` | texte | Identifiant du boîtier |
| `temp` | nombre | Température (°C) |
| `hum` | nombre | Humidité relative (%) |
| `gas_raw` | entier | Lecture brute A0 du MQ-2 (0–1023) |
| `pir` | booléen | Présence détectée |
| `rssi` | entier | Qualité Wi-Fi (dBm) |
| `uptime` | entier | Secondes depuis le démarrage |
| `ts` | entier | Horodatage Unix (NTP local) |

## Alerte (`POST /api/v1/alerts`)

| Champ | Type | Description |
|---|---|---|
| `device_id` | texte | Boîtier concerné |
| `source` | texte | `vision`, `anomaly`, `esp` |
| `type` | texte | ex. `intrusion`, `thermal_drift`, `gas_drift` |
| `severity` | texte | `info`, `warning`, `critical` |
| `value` | nombre | Valeur ou score à l'origine de l'alerte |
| `ts` | entier | Horodatage Unix |
| `details` | objet | Informations complémentaires (zone, durée de présence, image…) |

## Endpoints HTTP (via `https://sentinel-pi`)

| Méthode | Route | Rôle | Authentification |
|---|---|---|---|
| POST | `/api/v1/alerts` | Ingestion d'une alerte (vision, anomalies) | clé d'API |
| GET | `/api/v1/telemetry?from=` | Historique paginé | — à décider |
| POST | `/api/v1/commands` | Commande vers un boîtier (publiée sur `cmd`) | clé d'API / JWT |
| GET | `/api/v1/health` | État : CPU, RAM, disque, température du Pi, messages/s | — |
| WS | `/ws` | Flux temps réel vers le dashboard | — à décider |
| GET | `/video` | Flux MJPEG annoté (service vision) | — à décider |

## Points ouverts (questions aux coachs, docs/coachs.md)
- Format imposé de `POST /api/v1/alerts` et qui l'appelle.
