# Firmware ESP32-S3 — Momo (binômes : Michel au câblage, Lisa pour TLS)

Serveur : le PC portable (point d'accès Windows, **192.168.137.1**). Wi-Fi en **2,4 GHz** uniquement.

Carte : **ESP32-S3 N16R8** (16 Mo de flash, 8 Mo de PSRAM octale). Téléverser par le port USB-C **COM**.
Brochage : `include/pins.h` et `docs/cablage.md`. Contrat des messages : `docs/contracts.md`.

## Sketch du boîtier de la démo : `sentinel_lisa/` (Arduino IDE)

Câblage réel : PIR GPIO 5, MQ-2 GPIO 6 (ADC1, pont diviseur si 5 V), DHT11 GPIO 4, buzzer GPIO 7.

1. Sur le PC serveur : `python security\pki\pki.py --ip <adresse du PC>` si le boîtier joint le PC par une autre
   adresse que 192.168.137.1 (partage de connexion d'un téléphone…). Ça ne refait que le certificat du serveur
   (la CA ne change pas) et copie `certs.h` dans `sentinel_lisa/`. Puis `docker restart snx-mosquitto snx-nginx`.
2. Copier `sentinel_lisa/secrets.example.h` en `secrets.h` et le remplir : Wi-Fi (2,4 GHz, mot de passe **sans
   accent**), `MQTT_HOST` (adresse du PC), `MQTT_USE_TLS 1`, mot de passe `esp-01` (`configurer.py --afficher`).
3. Arduino IDE 2, carte « ESP32S3 Dev Module », bibliothèques PubSubClient, DHT sensor library, Adafruit Unified
   Sensor. Téléverser, moniteur série à 115200 bauds : `Connexion MQTT a … (TLS)... OK`, puis les envois.

| Bouton du dashboard | Effet sur le boîtier |
| --- | --- |
| Déclencher l'alarme | Sirène continue jusqu'à « Couper l'alarme » |
| Couper l'alarme | Silence, **même pendant une alerte gaz**, jusqu'au retour au calme (5 min au plus) ; l'incident reste à acquitter dans le dashboard |
| Passer en maintenance / en surveillance | Buzzer muet en maintenance ; `mode` le signale dans la télémétrie |
| Recalibrer | Réapprend l'air habituel du MQ-2 (2 s) |
| Redémarrer | Redémarrage (statut `offline` puis `online`) |

Une commande de plus de 30 s ou déjà exécutée (même `id`) est ignorée : un rejeu capturé ne fait rien.
En TLS, `echec, code = -2` suivi d'une ligne `TLS : …` = certificat refusé (adresse absente du certificat, ou
`certs.h` d'une autre CA) ; sans ligne TLS = serveur injoignable (adresse, pare-feu, Sentinel-X arrêté).

## platformio.ini (à créer à la racine de `firmware/` avec le code)

```ini
[env:sentinel]
platform = espressif32
board = esp32-s3-devkitc-1
framework = arduino
board_build.flash_size = 16MB
board_build.arduino.memory_type = qio_opi
build_flags = -DBOARD_HAS_PSRAM
monitor_speed = 115200
lib_deps =
  adafruit/DHT sensor library
  adafruit/Adafruit Unified Sensor
  arduino-libraries/LiquidCrystal
  adafruit/Adafruit NeoPixel
  knolleary/PubSubClient
  bblanchon/ArduinoJson
```

La CI compile le firmware dès que `firmware/platformio.ini` existe : ne le committer qu'avec un code qui compile.

## Architecture du firmware

| Tâche FreeRTOS | Cœur | Rôle |
| --- | --- | --- |
| Capteurs | 1 | DHT11 (2 s), MQ-2 en mV (`analogReadMilliVolts`, moyenne de 16), interruptions PIR, DO et tactile, température de la puce |
| Garde locale | 1 | EWMA + écart robuste + pente par capteur, `edge_score`, alarme réflexe, échantillonnage accéléré |
| Réseau | 0 | Wi-Fi, heure NTP du PC, MQTT TLS (`WiFiClientSecure` + `setCACert`, puis certificat client), tampon PSRAM rejoué, dernière volonté |
| Santé | 0 | Message `health` toutes les 30 s |

Écran LCD 1602 (2 × 16 caractères), rafraîchi par la tâche Santé, sans bloquer les capteurs :
ligne 1 = mesures (`T22C H45% G1.02`), ligne 2 = mode, alarme et sa cause, ou `HORS LIGNE` quand le tampon est actif.

Modes : `learning` (10 min), `armed`, `maintenance`. La configuration `sentinel/<id>/config` est enregistrée en NVS.
Voyant RGB : vert surveillance, bleu apprentissage, orange suspicion, rouge alarme, violet hors ligne, blanc maintenance.

## Arduino IDE : sketch de liaison (`sentinel_esp/`)

Pour l'équipe qui travaille dans l'Arduino IDE : `sentinel_esp/sentinel_esp.ino` relie le boîtier au PC serveur
(Wi-Fi, heure, MQTT) et publie `telemetry`, `event`, `health` et `status` au format de `docs/contracts.md`.

1. Carte « ESP32S3 Dev Module » ; USB CDC On Boot : Enabled ; Flash Size : 16MB ; PSRAM : OPI PSRAM.
2. Bibliothèques : PubSubClient, ArduinoJson (7.x), DHT sensor library, Adafruit Unified Sensor.
3. Copier `sentinel_esp/secrets.example.h` en `sentinel_esp/secrets.h` (ignoré par Git) et le remplir.
4. Vérifier les broches en tête du sketch (mêmes valeurs que `include/pins.h`).
5. Téléverser, moniteur série à 115200 : « Wi-Fi OK », « Heure OK », « MQTT OK », puis une ligne `->` par message.

Passage en TLS (mo2) : `MQTT_PORT 8883`, `MQTT_USE_TLS 1`. Le `certs.h` du même dossier (CA, certificat et clé d'`esp-01`)
est créé sur le PC serveur par `python tools\configurer.py` (ou `python security\pki\pki.py`) ; il n'est jamais commité.
TLS mutuel (li7) : en plus, `MQTT_USE_MTLS 1`.
La garde locale, le tampon PSRAM, l'effraction et les commandes viennent avec mo1, dans ce même sketch.

## Secrets
`include/secrets.h` et `include/certs.h` sont **ignorés par Git**.
```bash
cp include/secrets.example.h include/secrets.h
```
`certs.h` (CA, certificat et clé du boîtier) est généré par Lisa à partir de `security/certs/`.

## Ne pas activer
Secure Boot et Flash Encryption : fusibles irréversibles. Étape d'industrialisation, hors workshop.
