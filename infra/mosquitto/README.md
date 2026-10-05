# Mosquitto

| Fichier | Rôle | Versionné |
|---|---|---|
| `mosquitto.conf` | Production : TLS 8883 uniquement | oui |
| `mosquitto.dev.conf` | Lundi : 1883 en clair, authentifié | oui |
| `aclfile` | Droits par compte (moindre privilège) | oui |
| `passwd` | Comptes et mots de passe hachés | **non** (`.gitignore`) |

## Créer le fichier `passwd` (sur le Pi, dans `infra/`)

```bash
docker run --rm -v "$PWD/mosquitto:/m" eclipse-mosquitto:2.0 \
  sh -c 'mosquitto_passwd -c -b /m/passwd esp-01 "MDP_ESP" &&
         mosquitto_passwd -b /m/passwd api "MDP_API" &&
         mosquitto_passwd -b /m/passwd anomaly "MDP_ANOMALY" &&
         mosquitto_passwd -b /m/passwd monitor "MDP_MONITOR"'
sudo chown 1883:1883 mosquitto/passwd && sudo chmod 600 mosquitto/passwd
docker compose restart mosquitto
```

Les mots de passe `api` et `anomaly` doivent être identiques à ceux de `infra/.env`,
celui d'`esp-01` à celui de `firmware/include/secrets.h`.

## Tests rapides (depuis un laptop connecté au Wi-Fi du Pi)

```bash
# Lundi (1883)
mosquitto_sub -h 192.168.10.1 -p 1883 -u monitor -P 'MDP_MONITOR' -t 'sentinel/#' -v
# Dès mardi (8883)
mosquitto_sub -h 192.168.10.1 -p 8883 --cafile security/certs/ca.crt -u monitor -P 'MDP_MONITOR' -t 'sentinel/#' -v
# Preuve : un client anonyme doit être refusé
mosquitto_sub -h 192.168.10.1 -p 8883 --cafile security/certs/ca.crt -t '#'
```
