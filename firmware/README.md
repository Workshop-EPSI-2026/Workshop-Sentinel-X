# Firmware ESP32-S3 — Momo (binômes : Michel au câblage, Lisa pour TLS)

Carte : **ESP32-S3 N16R8** (16 Mo de flash, 8 Mo de PSRAM octale). Téléverser par le port USB-C **COM**.
Brochage : `include/pins.h` et `docs/cablage.md`. Contrat des messages : `docs/contracts.md`.

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
  adafruit/Adafruit SSD1306
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
| Réseau | 0 | Wi-Fi, MQTT TLS (`WiFiClientSecure` + `setCACert`, puis certificat client), tampon PSRAM rejoué, dernière volonté |
| Santé | 0 | Message `health` toutes les 30 s |

Modes : `learning` (10 min), `armed`, `maintenance`. La configuration `sentinel/<id>/config` est enregistrée en NVS.
Voyant RGB : vert surveillance, bleu apprentissage, orange suspicion, rouge alarme, violet hors ligne, blanc maintenance.

## Secrets
`include/secrets.h` et `include/certs.h` sont **ignorés par Git**.
```bash
cp include/secrets.example.h include/secrets.h
```
`certs.h` (CA, certificat et clé du boîtier) est généré par Lisa à partir de `security/certs/`.

## Ne pas activer
Secure Boot et Flash Encryption : fusibles irréversibles. Étape d'industrialisation, hors workshop.
