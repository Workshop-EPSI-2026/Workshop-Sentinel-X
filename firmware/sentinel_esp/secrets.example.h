// Modèle de secrets du sketch Arduino — copier en secrets.h (MÊME dossier, ignoré par Git) et remplir.
#pragma once

#define WIFI_SSID       "sentinel-x-gN"    // point d'accès mobile du PC serveur (2,4 GHz)
#define WIFI_PASSWORD   "CHANGE_ME"

#define MQTT_HOST       "192.168.137.1"   // PC serveur (adresse fixe du point d'accès Windows)
#define MQTT_PORT       1883              // avant TLS ; 8883 dès le passage en TLS
#define MQTT_USE_TLS    0                 // 1 dès que la CA de Lisa est dans certs.h
#define MQTT_USE_MTLS   0                 // 1 quand le certificat client du boîtier est prêt
#define MQTT_USER       "esp-01"          // ignoré en TLS mutuel (identité = CN du certificat)
#define MQTT_PASSWORD   "CHANGE_ME"         // sur le PC serveur : python tools\configurer.py --afficher (compte esp-01)

#define DEVICE_ID       "esp-01"
#define NTP_SERVER      "192.168.137.1"   // serveur de temps du PC (tools/serveur-pc.ps1 -Action Ntp)
