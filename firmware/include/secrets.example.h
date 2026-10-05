// Modèle de secrets — copier en secrets.h (ignoré par Git) et remplir.
#pragma once

#define WIFI_SSID      "sentinel-x"
#define WIFI_PASSWORD  "CHANGE_ME"

#define MQTT_HOST      "192.168.10.1"   // IP du Raspberry Pi (point d'accès)
#define MQTT_PORT      1883             // lundi ; 8883 dès le passage en TLS
#define MQTT_USER      "esp-01"
#define MQTT_PASSWORD  "CHANGE_ME"

#define DEVICE_ID      "esp-01"
#define NTP_SERVER     "192.168.10.1"   // chrony sur le Pi (vérification des certificats)
