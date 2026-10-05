# Réseau de table — Michel et Lisa

## Wi-Fi (point d'accès porté par le Raspberry Pi 5, `nmcli`)

| Paramètre | Valeur |
| --- | --- |
| SSID | `sentinel-x-gN` (N = numéro de groupe) |
| Bande / canal | 2,4 GHz, canal 1, 6 ou 11 (le moins chargé) |
| Sécurité | WPA2-AES, phrase de passe de 20 caractères minimum (hors dépôt) |
| Internet | Ethernet du Pi 5, pour les installations uniquement |

## Plan d'adressage (à confirmer selon la plage des coachs)

| Équipement | Nom | Adresse | Attribution |
| --- | --- | --- | --- |
| Raspberry Pi 5 (passerelle, serveur) | `sentinel-pi` | 192.168.10.1 | Fixe |
| Raspberry Pi 4 (repli, station d'audit) | `sentinel-pi4` | 192.168.10.2 | Fixe |
| ESP32-S3 | `esp-01` | 192.168.10.10 | Réservée, MAC : `__:__:__:__:__:__` |
| Postes de l'équipe | — | 192.168.10.100 à .120 | DHCP |

## Ports ouverts sur le serveur

| Port | Service | Depuis |
| --- | --- | --- |
| 22 | SSH (clé ed25519 uniquement) | Sous-réseau admin |
| 443 | HTTPS / WSS (nginx) | Réseau de table |
| 8883 | MQTTS (boîtiers) | Réseau de table |
| *tout le reste* | refusé (UFW) | — |

Le port 8884 (MQTT des services) existe uniquement à l'intérieur de Docker et n'est jamais publié.
Docker contourne UFW pour les ports publiés : seuls 443 et 8883 sont publiés, et la CI le vérifie.

## Bascule sur le Pi 4 (à répéter mercredi, objectif < 10 min)

1. Éteindre le point d'accès du Pi 5 (ou le Pi 5).
2. Sur le Pi 4 : activer le profil `nmcli` du point d'accès avec l'adresse 192.168.10.1.
3. Copier `infra/.env`, `infra/mosquitto/passwd`, `security/certs/` (clé USB), puis `docker compose up -d`.
4. Vérifier que l'ESP32-S3 se reconnecte seul et que le tampon se vide.
