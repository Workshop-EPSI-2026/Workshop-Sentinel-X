# Mosquitto

| Fichier | Rôle | Versionné |
|---|---|---|
| `mosquitto.dev.conf` | Socle : 1883 en clair, authentifié | oui |
| `mosquitto.tls.conf` | TLS sur 8883 (boîtier, vision) et 8884 (services Docker) | oui |
| `mosquitto.mtls.conf` | Cible : TLS mutuel sur 8883, certificat par équipement | oui |
| `aclfile` | Droits par compte (moindre privilège) : `esp-01`, `vision`, `api`, `anomaly`, `monitor` | oui |
| `passwd` | Comptes et mots de passe hachés | **non** (`.gitignore`) |

## Créer le fichier `passwd`

**Méthode automatique (recommandée)** : `python tools\configurer.py` crée `infra\.env` et `passwd` ensemble, avec les
mêmes mots de passe, sans Docker. `python tools\configurer.py --afficher` redonne ceux d'`esp-01` et de `monitor`.

Méthode manuelle (PowerShell, dossier `infra`, Docker Desktop démarré) :

```powershell
cd infra
docker run --rm -v "${PWD}\mosquitto:/m" eclipse-mosquitto:2.0 sh -c `
  'mosquitto_passwd -c -b /m/passwd esp-01 "MDP_ESP" &&
   mosquitto_passwd -b /m/passwd vision "MDP_VISION" &&
   mosquitto_passwd -b /m/passwd api "MDP_API" &&
   mosquitto_passwd -b /m/passwd anomaly "MDP_ANOMALY" &&
   mosquitto_passwd -b /m/passwd monitor "MDP_MONITOR"'
docker compose restart mosquitto
```

Sous Linux ou sur un Raspberry Pi, même commande avec `-v "$PWD/mosquitto:/m"` et des `\` en fin de ligne, puis
`sudo chown 1883:1883 mosquitto/passwd && sudo chmod 600 mosquitto/passwd`.

Les mots de passe `api`, `anomaly` et `vision` doivent être identiques à ceux de `infra/.env`
(`MQTT_API_PASSWORD`, `MQTT_ANOMALY_PASSWORD`, `MQTT_VISION_PASSWORD`), celui d'`esp-01` à celui de
`firmware/include/secrets.h`. Mosquitto affiche un avertissement sur les droits du fichier sous Windows : sans effet.

## Tests rapides (depuis le PC serveur, ou un poste connecté au point d'accès : remplacer localhost par 192.168.137.1)

```powershell
# Socle (1883)
mosquitto_sub -h localhost -p 1883 -u monitor -P "MDP_MONITOR" -t "sentinel/#" -v
# TLS (8883) : le certificat serveur couvre localhost, 127.0.0.1, 192.168.137.1 et sentinel-pc
mosquitto_sub -h localhost -p 8883 --cafile security\certs\ca.crt -u monitor -P "MDP_MONITOR" -t "sentinel/#" -v
# Preuve : un client anonyme doit être refusé
mosquitto_sub -h localhost -p 8883 --cafile security\certs\ca.crt -t "#"
# Preuve : cinq mauvais mots de passe en une minute produisent un incident cyber (Sentinel Brain lit le journal)
1..5 | ForEach-Object { mosquitto_pub -h localhost -p 8883 --cafile security\certs\ca.crt -u esp-01 -P faux -t x -m x }
```

## Choisir la configuration
Dans `infra/.env` : `MOSQUITTO_CONF=mosquitto.tls.conf` puis `mosquitto.mtls.conf`, puis `docker compose up -d`.
En TLS mutuel, chaque client du port 8883 (boîtier, vision, tests) présente son certificat :
```powershell
mosquitto_sub -h localhost -p 8883 --cafile security\certs\ca.crt `
  --cert security\certs\monitor.crt --key security\certs\monitor.key -t "sentinel/#" -v
```
La vision lit alors `MQTT_CERT` et `MQTT_KEY` (certificat `vision`, CN = `vision`).
