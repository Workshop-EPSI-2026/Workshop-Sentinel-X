# Réseau de table — Michel et Lisa

Option B retenue : **le PC portable est le serveur**. Il porte le Wi-Fi de table (point d'accès mobile Windows),
Docker Desktop (broker, base, API, dashboard, Sentinel Brain) et la vision sur la webcam. Préparation en une commande
(PowerShell administrateur) : `tools\serveur-pc.ps1` — pare-feu, NTP, point d'accès, vérification.

## Wi-Fi (point d'accès mobile Windows)

| Paramètre | Valeur |
| --- | --- |
| SSID | `sentinel-x-gN` (N = numéro de groupe) |
| Bande | **2,4 GHz obligatoire** (l'ESP32-S3 ne voit pas le 5 GHz) |
| Sécurité | WPA2, phrase de passe de 20 caractères minimum (hors dépôt) |
| Source | Le PC doit être relié à un réseau (Wi-Fi de l'école ou Ethernet) pour activer le point d'accès ; Sentinel-X n'utilise pas Internet |
| Clients | 8 au maximum (limite Windows) : largement suffisant |

### Variante : partage de connexion d'un téléphone

Le PC serveur et le boîtier se connectent au même partage de connexion (2,4 GHz, mot de passe sans accent).
L'adresse du PC est celle que donne `ipconfig` (carte Wi-Fi), par exemple `10.68.118.203` : la mettre dans
`MQTT_HOST` du boîtier et dans le certificat du serveur (`python security\pki\pki.py --ip 10.68.118.203`, puis
`docker restart snx-mosquitto snx-nginx`). Vérifier l'adresse avant chaque démo : un téléphone peut en changer.
Les règles du pare-feu (`serveur-pc.ps1 -Action PareFeu`) acceptent aussi le sous-réseau local : rien à changer.

## Plan d'adressage

Windows fixe lui-même le réseau du point d'accès : **192.168.137.0/24**, le PC en **192.168.137.1**.

| Équipement | Nom | Adresse | Attribution |
| --- | --- | --- | --- |
| PC serveur | `sentinel-pc` | 192.168.137.1 | Fixe (point d'accès Windows) |
| ESP32-S3 | `esp-01` | 192.168.137.x | DHCP du point d'accès ; l'ESP n'a besoin que de l'adresse du serveur |
| Postes de l'équipe (tests, pentest) | — | 192.168.137.x | DHCP |

## Ports ouverts sur le PC

| Port | Service | Depuis |
| --- | --- | --- |
| 443 | HTTPS / WSS (nginx) | Réseau du point d'accès uniquement |
| 8883 | MQTTS (boîtier) | Réseau du point d'accès uniquement |
| 123/UDP | NTP (heure de l'ESP) | Réseau du point d'accès uniquement |
| 1883 | MQTT en clair, **avant TLS seulement** (`serveur-pc.ps1 -Action PareFeu -Dev`) | Réseau du point d'accès |
| *tout le reste* | refusé (pare-feu Windows) | — |

Le port 8884 (MQTT des services) existe uniquement dans Docker et n'est jamais publié. Le flux vidéo de la vision
(8001) n'écoute que sur 127.0.0.1 : on le voit depuis le réseau seulement à travers nginx, en HTTPS (`/video`).
La CI refuse tout port publié autre que 443 et 8883.

## Plan B : routeur de table

Si le point d'accès Windows refuse de démarrer (carte Wi-Fi incompatible, pas de réseau source) : un petit routeur
Wi-Fi, réglé ainsi pour que **rien ne change côté ESP** :

1. Réseau local du routeur en 192.168.137.0/24, routeur en 192.168.137.254.
2. Réservation DHCP du PC (son adresse MAC) en **192.168.137.1**.
3. Même SSID et même phrase de passe que le point d'accès.

## Bascule sur le PC de secours (à répéter mercredi, objectif < 10 min)

1. Sur le PC de secours (n'importe quel autre poste qui passe `verifier-serveur.cmd`) : dépôt à jour, `installer.cmd`
   déjà fait la veille.
2. Copier (clé USB) `infra\.env`, `infra\mosquitto\passwd`, `security\certs\`.
3. `tools\serveur-pc.ps1` (administrateur) avec le même SSID et la même phrase de passe, puis éteindre le point
   d'accès du premier PC.
4. `tools\demarrer.ps1` ; vérifier que l'ESP32-S3 se reconnecte seul et que son tampon se vide (mesures `replay`).
