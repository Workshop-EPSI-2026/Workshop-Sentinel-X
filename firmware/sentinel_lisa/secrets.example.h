// Reglages du boitier : copier en secrets.h (meme dossier, ignore par Git) et remplir.
#pragma once

#define WIFI_SSID      "nom-du-reseau"          // 2,4 GHz, mot de passe SANS accent
#define WIFI_PASSWORD  "CHANGE_ME"

#define MQTT_HOST      "192.168.137.1"          // adresse du PC serveur sur ce reseau (ipconfig) ; en TLS, elle doit
                                                // figurer dans le certificat : python security\pki\pki.py --ip ADRESSE
#define MQTT_USE_TLS   1                        // 1 : chiffre (8883, certs.h requis) ; 0 : en clair (1883, mise au point)
#define MQTT_PORT      (MQTT_USE_TLS ? 8883 : 1883)
#define MQTT_USER      "esp-01"
#define MQTT_PASSWORD  "CHANGE_ME"              // python tools\configurer.py --afficher (ligne esp-01)

#define DEVICE_ID      "esp-01"
#define NTP_SERVER     "pool.ntp.org"           // ou l'adresse du PC si serveur-pc.ps1 -Action Ntp est fait
