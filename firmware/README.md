# Firmware ESP8266 — responsable : Momo (binômes : Michel câblage, Lisa TLS)

Projet PlatformIO (`platformio.ini` à la racine de ce dossier) ou Arduino IDE.
Bibliothèques : DHT sensor library, Adafruit SSD1306, PubSubClient, ArduinoJson.

## Secrets
`include/secrets.h` est **ignoré par Git**. Le créer à partir du modèle :
```bash
cp include/secrets.example.h include/secrets.h
```
Le certificat de la CA (`ca.crt`, public) est embarqué via un en-tête généré par Lisa,
lui aussi non versionné (`include/ca_cert.h`).

## Brochage
Voir `docs/cablage.md` (Momo + Michel). Éviter D3, D4, D8 pour le PIR et le buzzer ;
OLED sur D1/D2 ; MQ-2 en 5 V via pont diviseur vers A0.
