# Contrat d'interface — Sentinel-X v2

> Référence d'intégration. **Toute modification passe par une Pull Request et est annoncée au groupe.**
> Horodatages : secondes Unix (UTC), fournis par le NTP local du PC serveur.

## Réseau

| Élément | Valeur |
| --- | --- |
| Serveur | PC Windows 11 `sentinel-pc`, 192.168.137.1 (point d'accès mobile) |
| Boîtier | ESP32-S3 `esp-01`, adresse DHCP ; se connecte toujours à 192.168.137.1 |
| MQTT boîtiers | 8883 TLS (1883 authentifié le lundi uniquement), TLS mutuel en cible |
| MQTT services | 8884 TLS, interne à Docker |
| Web | 443 HTTPS / WSS |

## Topics MQTT

`<id>` = identifiant du boîtier = nom du compte MQTT = CN de son certificat client (ex. `esp-01`).

| Topic | Émetteur | Abonnés | QoS | Conservé | Contenu |
| --- | --- | --- | --- | --- | --- |
| `sentinel/<id>/telemetry` | Boîtier, toutes les 2 s (500 ms en suspicion) | API, Brain | 0 | non | Mesures |
| `sentinel/<id>/event` | Boîtier, immédiat | API, Brain | 1 | non | PIR, effraction, seuil gaz matériel, alarme locale, démarrage |
| `sentinel/<id>/health` | Boîtier, toutes les 30 s | API, Brain | 0 | non | Santé du boîtier |
| `sentinel/<id>/status` | Boîtier (dernière volonté : `offline`) | API, Brain | 1 | oui | `online` / `offline` |
| `sentinel/<id>/cmd` | API | Boîtier | 1 | non | Commandes |
| `sentinel/<id>/config` | API | Boîtier | 1 | oui | Partie « boîtier » du profil de site |
| `sentinel/site/config` | API | Brain | 1 | oui | Profil de site complet |
| `sentinel/brain/score` | Brain, toutes les 2 s | API | 0 | non | Scores en direct |

## Télémétrie

| Champ | Type | Description |
| --- | --- | --- |
| `device_id` | texte | Identifiant du boîtier |
| `seq` | entier | Compteur croissant, remis à zéro au démarrage (`boot_id` change) |
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

## Commande (`cmd`)

`{"cmd": "alarm", "on": true}` · `{"cmd": "led", "color": "red"}` · `{"cmd": "mode", "value": "maintenance"}` ·
`{"cmd": "recalibrate"}` · `{"cmd": "reboot"}` — toujours avec `id` (unique) et `ts`. Le boîtier ignore une commande
plus vieille que 30 s ou dont l'`id` a déjà été vu.

## Alerte / incident (`POST /api/v1/alerts`)

| Champ | Type | Description |
| --- | --- | --- |
| `device_id` | texte | Boîtier concerné |
| `source` | texte | `vision`, `brain`, `edge` |
| `domain` | texte | `environment`, `physical`, `cyber`, `maintenance` |
| `type` | texte | `intrusion_confirmed`, `intrusion_suspected`, `loitering`, `sabotage`, `fire_risk`, `gas_leak`, `jamming_suspected`, `cyber_attack`, `sensor_fault` |
| `severity` | texte | `info`, `warning`, `critical` |
| `score` | nombre | 0 à 100 |
| `eta_min` | nombre ou null | Minutes avant le niveau critique (prévision) |
| `ts` | entier | Horodatage |
| `explanation` | texte | Phrase lisible |
| `factors` | liste | `[{"name": "gas_ratio", "value": 1.38, "contribution": 0.62}, …]` |
| `details` | objet | Zone, durée de présence, image, compteurs… |

## Endpoints HTTP (via `https://192.168.137.1`, ou `https://localhost` sur le PC serveur)

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
| GET | `/video` | Flux MJPEG annoté | Opérateur |

## Points ouverts (docs/coachs.md)
- Format imposé de `POST /api/v1/alerts` par les coachs : à confirmer. Si imposé, ce contrat s'y aligne.
