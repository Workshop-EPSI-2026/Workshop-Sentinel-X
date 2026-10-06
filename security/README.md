# Sécurité — Lisa (binômes : Constantin, Momo, Jeffrick pour la détection cyber)

## PKI locale (OpenSSL, ECDSA P-256)
Script dans `security/pki/` (versionné **sans** aucune clé). Sortie dans `security/certs/` (**jamais commité**).

| Fichier | Usage |
| --- | --- |
| `ca.crt` / `ca.key` | Autorité locale ; `ca.key` reste sur une clé USB, hors du PC serveur si possible |
| `server.crt` / `server.key` | Mosquitto (8883, 8884) et nginx (443) |
| `esp-01.crt` / `esp-01.key` | Certificat client du boîtier (TLS mutuel), CN = `esp-01` |
| `monitor.crt` / `monitor.key` | Certificat client des tests (`mosquitto_sub`), CN = `monitor` |

SAN du certificat serveur : `IP:192.168.137.1`, `IP:127.0.0.1`, `DNS:sentinel-pc`, `DNS:localhost`, `DNS:mosquitto`
(`localhost` : la vision appelle l'API par nginx depuis le PC serveur).
Le CN d'un certificat client devient son nom d'utilisateur MQTT : il doit correspondre à un bloc de `infra/mosquitto/aclfile`.
Pour le firmware : générer `firmware/include/certs.h` (CA, certificat et clé du boîtier), ignoré par Git.

## Droits sur les clés (PC serveur Windows)
Docker Desktop ne transmet pas les droits du système de fichiers aux conteneurs : `CERTS_GID`, `chgrp` et `chmod`
sont sans effet. `security/certs/` est protégé par la session Windows (mot de passe, PC verrouillé en cas d'absence).
OpenSSL est fourni avec Git for Windows : lancer le script de `security/pki/` depuis Git Bash.

## Étapes
1. CA + certificat serveur + NTP du PC serveur (lundi, `docs/reseau.md`).
2. TLS : `MOSQUITTO_CONF=mosquitto.tls.conf`, fermeture de 1883 (mardi).
3. Certificats clients, puis `MOSQUITTO_CONF=mosquitto.mtls.conf` (mercredi, si le socle est stable).
4. Durcissement de l'hôte (pare-feu Windows, profil Public, partage désactivé, pas de SSH), Nmap avant/après.
5. Signaux cyber vers Sentinel Brain avec Jeffrick (journal Mosquitto, rafales 401/429, rejeu).

## Preuves (docs/preuves/)
Wireshark 1883 clair contre 8883 chiffré · client sans certificat refusé · Nmap avant/après · payload invalide rejeté ·
incident cyber généré pendant une attaque · rapport gitleaks.
