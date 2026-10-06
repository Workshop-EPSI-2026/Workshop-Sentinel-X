# Sécurité — Lisa (binômes : Constantin, Momo, Jeffrick pour la détection cyber)

## PKI locale (OpenSSL, ECDSA P-256)
Script dans `security/pki/` (versionné **sans** aucune clé). Sortie dans `security/certs/` (**jamais commité**).
OpenSSL est fourni avec Git pour Windows (`C:\Program Files\Git\usr\bin\openssl.exe`).

| Fichier | Usage |
| --- | --- |
| `ca.crt` / `ca.key` | Autorité locale ; `ca.key` reste sur une clé USB, **pas** sur le PC serveur |
| `server.crt` / `server.key` | Mosquitto (8883, 8884) et nginx (443) |
| `esp-01.crt` / `esp-01.key` | Certificat client du boîtier (TLS mutuel), CN = `esp-01` |
| `vision.crt` / `vision.key` | Certificat client du service vision (TLS mutuel), CN = `vision` |
| `monitor.crt` / `monitor.key` | Certificat client des tests (`mosquitto_sub`), CN = `monitor` |

SAN du certificat serveur : `IP:192.168.137.1`, `IP:127.0.0.1`, `DNS:localhost`, `DNS:sentinel-pc`, `DNS:mosquitto`,
`DNS:host.docker.internal`. Le boîtier se connecte à 192.168.137.1, la vision et les tests du PC à `localhost`, les
services Docker à `mosquitto` : tous doivent figurer dans le certificat, sinon la vérification TLS échoue.
Le CN d'un certificat client devient son nom d'utilisateur MQTT : il doit correspondre à un bloc de `infra/mosquitto/aclfile`.
Pour le firmware : générer `firmware/include/certs.h` (CA, certificat et clé du boîtier), ignoré par Git.

Vérifier un certificat serveur : `openssl x509 -in security\certs\server.crt -noout -ext subjectAltName`.

## Droits sur les clés
- **PC Windows** : rien à régler pour Docker Desktop. Restreindre le dossier à l'utilisateur :
  `icacls security\certs /inheritance:r /grant:r "%USERNAME%:(OI)(CI)F"`.
- **Linux / Raspberry Pi** (portage) :
  ```bash
  sudo groupadd -g 2000 sentinel-certs
  sudo chgrp -R 2000 security/certs && sudo chmod 640 security/certs/*.key && sudo chmod 644 security/certs/*.crt
  ```

## Étapes
1. CA + certificat serveur (SAN ci-dessus) ; heure : serveur NTP du PC (`tools\serveur-pc.ps1 -Action Ntp`).
2. TLS : `MOSQUITTO_CONF=mosquitto.tls.conf`, fermeture de 1883 (et retrait de la règle de pare-feu 1883).
3. Certificats clients (`esp-01`, `vision`, `monitor`), puis `MOSQUITTO_CONF=mosquitto.mtls.conf`, si le socle est stable.
4. Durcissement du PC serveur (`docs/securite.md`), Nmap avant/après depuis un autre poste du point d'accès.
5. Signaux cyber vers Sentinel Brain avec Jeffrick : accès refusés du journal Mosquitto (déjà actifs), rafales 401/429.

## Preuves (docs/preuves/)
Wireshark 1883 clair contre 8883 chiffré · client sans certificat refusé · Nmap avant/après · payload invalide rejeté ·
incident cyber généré pendant une attaque (force brute MQTT, rejeu) · rapport gitleaks.
