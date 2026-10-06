# Mosquitto

| Fichier | Rôle | Versionné |
|---|---|---|
| `mosquitto.dev.conf` | Lundi : 1883 en clair, authentifié | oui |
| `mosquitto.tls.conf` | Mardi : TLS sur 8883 (boîtiers) et 8884 (services) | oui |
| `mosquitto.mtls.conf` | Cible : TLS mutuel sur 8883, certificat par boîtier | oui |
| `aclfile` | Droits par compte (moindre privilège) | oui |
| `passwd` | Comptes et mots de passe hachés | **non** (`.gitignore`) |

## Créer le fichier `passwd` (sur le PC serveur, PowerShell, dans `infra\`)

```powershell
docker run --rm -v "${PWD}\mosquitto:/m" eclipse-mosquitto:2.0 sh -c `
  'mosquitto_passwd -c -b /m/passwd esp-01 ''MDP_ESP'' && mosquitto_passwd -b /m/passwd api ''MDP_API'' && mosquitto_passwd -b /m/passwd anomaly ''MDP_ANOMALY'' && mosquitto_passwd -b /m/passwd monitor ''MDP_MONITOR'''
docker compose restart mosquitto
```

Mots de passe sans apostrophe ni espace. Docker Desktop ignore les droits du fichier (pas de `chown` ni de `chmod`) :
Mosquitto peut signaler que `passwd` est lisible par tous, sans conséquence ici.

Les mots de passe `api` et `anomaly` doivent être identiques à ceux de `infra/.env`,
celui d'`esp-01` à celui de `firmware/include/secrets.h`.

## Tests rapides (depuis un laptop connecté au point d'accès du PC serveur)

```bash
# Lundi (1883)
mosquitto_sub -h 192.168.137.1 -p 1883 -u monitor -P 'MDP_MONITOR' -t 'sentinel/#' -v
# Dès mardi (8883, boîtiers ; les tests se font sur ce port depuis un laptop)
mosquitto_sub -h 192.168.137.1 -p 8883 --cafile security/certs/ca.crt -u monitor -P 'MDP_MONITOR' -t 'sentinel/#' -v
# Preuve : un client anonyme doit être refusé
mosquitto_sub -h 192.168.137.1 -p 8883 --cafile security/certs/ca.crt -t '#'
```

## Choisir la configuration
Dans `infra/.env` : `MOSQUITTO_CONF=mosquitto.tls.conf` puis `mosquitto.mtls.conf`, puis `docker compose up -d`.
En TLS mutuel, un test depuis un laptop exige un certificat client :
```bash
mosquitto_sub -h 192.168.137.1 -p 8883 --cafile security/certs/ca.crt \
  --cert security/certs/monitor.crt --key security/certs/monitor.key -t 'sentinel/#' -v
```
