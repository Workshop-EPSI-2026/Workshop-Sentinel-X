// Modèle de secrets — copier en secrets.h (ignoré par Git) et remplir.
#pragma once

#define WIFI_SSID       "sentinel-x-gN"
#define WIFI_PASSWORD   "CHANGE_ME"

#define MQTT_HOST       "192.168.10.1"   // Raspberry Pi 5 (le Pi 4 reprend cette adresse en cas de bascule)
#define MQTT_PORT       1883             // lundi ; 8883 dès le passage en TLS
#define MQTT_USE_TLS    0                // 1 dès mardi (CA dans certs.h)
#define MQTT_USE_MTLS   0                // 1 quand le certificat client du boîtier est prêt
#define MQTT_USER       "esp-01"         // ignoré en TLS mutuel (identité = CN du certificat)
#define MQTT_PASSWORD   "CHANGE_ME"

#define DEVICE_ID       "esp-01"
#define NTP_SERVER      "192.168.10.1"   // chrony sur le Pi
