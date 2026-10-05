# Réseau de table — Michel et Lisa (tâche g6)

## Wi-Fi (point d'accès porté par le Raspberry Pi, `nmcli`)

| Paramètre | Valeur |
|---|---|
| SSID | `sentinel-x-gN` (N = numéro de groupe) |
| Bande / canal | 2,4 GHz, canal 1, 6 ou 11 (différent des tables voisines) |
| Sécurité | WPA2-AES, phrase de passe de 20 caractères minimum (hors dépôt) |
| Accès Internet du Pi | Ethernet (prise de la salle ou partage depuis un laptop) |

## Plan d'adressage (à confirmer selon la plage des coachs)

| Équipement | Adresse | Attribution |
|---|---|---|
| Raspberry Pi 5 (passerelle, serveur) | 192.168.10.1 | Fixe |
| ESP8266 `esp-01` | 192.168.10.10 | Réservée par adresse MAC : `__:__:__:__:__:__` |
| Postes admin et équipe | 192.168.10.100 – .120 | DHCP |

## Ports ouverts sur le Pi

| Port | Service | Depuis |
|---|---|---|
| 22 | SSH (clé uniquement) | Sous-réseau admin |
| 443 | HTTPS / WSS (nginx) | Réseau de table |
| 8883 | MQTTS (Mosquitto) | Réseau de table |
| *tout le reste* | refusé (UFW) | — |

> Rappel : Docker contourne UFW pour les ports publiés. Le `docker-compose.yml` ne publie
> que 443 et 8883, et la CI le vérifie. Toujours confirmer au Nmap.
