# Sécurité — responsable : Lisa (binômes : Constantin, Momo)

## Certificats
Générés dans `security/certs/` (**jamais commité**) par le script de la tâche l1
(`security/pki/`, versionné **sans** les clés). Fichiers attendus :

| Fichier | Utilisé par |
|---|---|
| `ca.crt` | API, service d'anomalies, firmware, clients de test |
| `server.crt` / `server.key` | Mosquitto (8883) et nginx (443) |

Le certificat serveur doit contenir dans son SAN : `IP:192.168.10.1`, `DNS:sentinel-pi`
et `DNS:mosquitto` (nom utilisé par les conteneurs à l'intérieur du réseau Docker).

## Droits sur la clé privée (sur le Pi)
Les conteneurs Mosquitto et nginx tournent sans root ; ils lisent la clé via un groupe dédié :
```bash
sudo groupadd -g 2000 sentinel-certs
sudo chgrp -R 2000 security/certs
sudo chmod 640 security/certs/server.key
sudo chmod 644 security/certs/*.crt
```

## Preuves à produire (docs/preuves/)
Wireshark 1883 en clair vs 8883 chiffré, Nmap avant/après hardening, client anonyme refusé,
payload invalide rejeté par l'API, appel sans clé refusé, rapport gitleaks.
