# Réseau de table et PC serveur — Michel et Lisa

Il n'y a pas de Raspberry Pi : toute la partie serveur est hébergée sur un **PC Windows 11** (`sentinel-pc`).
Ce PC est à la fois le point d'accès Wi-Fi, l'hôte Docker (Docker Desktop, moteur WSL2) et le poste de la vision.

## Wi-Fi (point d'accès mobile de Windows)

*Paramètres → Réseau et Internet → Point d'accès mobile*

| Paramètre | Valeur |
| --- | --- |
| SSID | `sentinel-x-gN` (N = numéro de groupe) |
| Bande | **2,4 GHz** obligatoire (l'ESP32-S3 ne gère pas le 5 GHz) |
| Sécurité | WPA2, phrase de passe de 20 caractères minimum (hors dépôt) |
| Partage | « Partager via Wi-Fi » ; connexion partagée : Ethernet ou Wi-Fi de l'école, pour les installations |
| Économie d'énergie | « Désactiver quand aucun appareil n'est connecté » : **désactivé** |
| Appareils | 8 au maximum (limite de Windows) |

Le point d'accès Windows ne permet pas de choisir le canal ni de réserver une adresse par MAC.
Il ne démarre pas tout seul au redémarrage du PC : il faut le réactiver à la main, avant la stack.
Internet est disponible (confirmé par les coachs) : le PC reste connecté au réseau de l'école et partage cette connexion
par le point d'accès. L'ESP32-S3 n'a pas besoin d'Internet, et la démo doit tourner même si la connexion de l'école coupe.

## Plan d'adressage

Réseau fixé par Windows (partage de connexion) : **192.168.137.0/24**.

| Équipement | Nom | Adresse | Attribution |
| --- | --- | --- | --- |
| PC serveur (passerelle, Docker, vision) | `sentinel-pc` | 192.168.137.1 | Fixe (Windows) |
| ESP32-S3 | `esp-01` | DHCP, lue dans la page Point d'accès mobile | MAC : `__:__:__:__:__:__` |
| Postes de l'équipe (tests, audit) | — | DHCP | — |

Les boîtiers se connectent toujours à **192.168.137.1** : leur propre adresse n'a pas besoin d'être fixe.

## Ports ouverts sur le PC serveur

| Port | Service | Depuis |
| --- | --- | --- |
| 443/tcp | HTTPS / WSS (nginx dans Docker) | Réseau de table |
| 8883/tcp | MQTTS (Mosquitto dans Docker, boîtiers) | Réseau de table |
| 123/udp | NTP (service Temps Windows), heure des boîtiers pour TLS | Réseau de table |
| 1883/tcp | MQTT en clair, **lundi uniquement** (surcharge `docker-compose.dev.yml`) | Réseau de table |
| *tout le reste* | refusé (pare-feu Windows Defender) | — |

Le port 8884 (MQTT des services) n'existe qu'à l'intérieur de Docker et n'est jamais publié.
La vision écoute sur `127.0.0.1:8001`, jamais sur le réseau : seul nginx la relaie (`/video`).
Docker Desktop publie les ports par son propre processus et contourne les règles par port du pare-feu.
Seuls 443 et 8883 sont publiés, et la CI le vérifie. Nmap depuis un poste de l'équipe sert de preuve.

## Préparer le PC serveur (une fois, lundi)

1. **Docker Desktop** avec le moteur WSL2 ; *Start Docker Desktop when you sign in* coché.
   Les conteneurs redémarrent seuls (`restart: unless-stopped`).
2. **Git** et **Python 3.12** (pour la vision hors Docker).
3. **Veille désactivée sur secteur** (sinon la démo s'arrête) et PC toujours branché :
   ```powershell
   powercfg /change standby-timeout-ac 0
   powercfg /change hibernate-timeout-ac 0
   ```
4. **Windows Update** suspendu pour la semaine, pour éviter un redémarrage imposé pendant la démo.
5. **Serveur NTP local** (PowerShell administrateur) :
   ```powershell
   reg add HKLM\SYSTEM\CurrentControlSet\Services\W32Time\TimeProviders\NtpServer /v Enabled /t REG_DWORD /d 1 /f
   reg add HKLM\SYSTEM\CurrentControlSet\Services\W32Time\Config /v AnnounceFlags /t REG_DWORD /d 5 /f
   sc.exe config w32time start= auto
   Restart-Service w32time
   ```
6. **Pare-feu** (PowerShell administrateur) : refuser par défaut, autoriser 443, 8883 et 123/udp :
   ```powershell
   New-NetFirewallRule -DisplayName "Sentinel-X HTTPS" -Direction Inbound -Protocol TCP -LocalPort 443  -Action Allow
   New-NetFirewallRule -DisplayName "Sentinel-X MQTTS" -Direction Inbound -Protocol TCP -LocalPort 8883 -Action Allow
   New-NetFirewallRule -DisplayName "Sentinel-X NTP"   -Direction Inbound -Protocol UDP -LocalPort 123  -Action Allow
   ```
   Le réseau du point d'accès doit rester en profil **Public** : partage de fichiers et découverte réseau désactivés.
7. Point d'accès mobile configuré comme ci-dessus ; tester avec un téléphone, puis avec l'ESP32-S3.

## Redémarrage du PC (à répéter mercredi, objectif < 10 min)

Ce test remplace l'ancienne bascule sur un Pi de repli : c'est la panne la plus probable le jour de la démo.

1. Redémarrer le PC serveur, ouvrir la session.
2. Réactiver le point d'accès mobile ; Docker Desktop démarre seul, `docker compose ps` doit afficher « healthy ».
3. Relancer la vision (`ai\vision\run-windows.ps1`).
4. Vérifier que l'ESP32-S3 se reconnecte seul et que son tampon PSRAM se vide sans trou au dashboard.

En dernier recours, le simulateur (`tools/simulator.py`) remplace l'ESP32-S3.
