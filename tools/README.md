# Outils

| Fichier | Rôle | Responsable |
|---|---|---|
| `bootstrap_github.py` | Crée le dépôt GitHub, les membres, labels, jalons, issues et le Kanban ; `--sync` met à jour les issues | Constantin |
| `simulator.py` | Simulateur d'ESP32-S3 au format du contrat v2 (tâche j1) | Jeffrick |
| `setup-poste.ps1` | Installe l'environnement commun d'un poste Windows, par rôle | Tous |
| `doctor.py` | Contrôle un poste (`--role`) ou un Raspberry Pi (`--pi`) : [OK], [!!], [KO] et la correction | Tous |
| `lock_deps.py` | Régénère les verrous de dépendances (`--check` en CI) | Jeffrick, Constantin |

## Simulateur (`simulator.py`)

Installation : déjà fait par `setup-poste.ps1` (sinon `pip install -r tools/requirements.txt`).

Il publie exactement ce que publiera le boîtier : `telemetry` (2 s, 500 ms quand le gaz monte), `event`,
`health` (30 s) et `status` (dernière volonté `offline`), avec `seq`, `boot_id`, la quantification du DHT11
(pas de 1 °C) et le tampon rejoué après une coupure (`replay: true`).

| Scénario | Ce qui se passe |
| --- | --- |
| `normal` | Régime normal, sans fin (Ctrl+C pour arrêter) |
| `drift` | Température qui monte lentement, gaz stable |
| `gas_leak` | Ratio gaz qui monte vers 2, température stable |
| `fire` | Température et gaz qui montent ensemble, humidité qui baisse |
| `intrusion` | Passages répétés devant le PIR |
| `tamper` | Main sur le couvercle (événement `tamper`) |
| `replay` | Attaque : renvoi à l'identique d'anciens messages |
| `jamming` | RSSI qui s'effondre, coupure, puis rejeu du tampon |
| `all` | Tous les scénarios à la suite |

Chaque scénario enchaîne régime normal (`--warmup`, 15 min par défaut), anomalie (`--anomaly`, 5 min) et retour au calme
(`--cooldown`, 5 min). Les durées sont en secondes **simulées** ; `--speed 60` fait passer une minute par seconde.

```powershell
# Broker local de test
docker run --rm -p 1883:1883 eclipse-mosquitto:2.0 mosquitto -c /mosquitto-no-auth.conf
python tools/simulator.py --scenario gas_leak --speed 10 -v

# Raspberry Pi, lundi (1883 authentifié, compte esp-01)
python tools/simulator.py --host 192.168.10.1 --user esp-01 --password "<mdp>" --scenario all --speed 10

# Raspberry Pi, dès mardi (TLS 8883)
python tools/simulator.py --host 192.168.10.1 --port 8883 --tls --cafile security/certs/ca.crt --user esp-01 --password "<mdp>"

# Jeu de données étiqueté pour Sentinel Brain (sans broker, instantané, reproductible)
python tools/simulator.py --no-mqtt --scenario all --speed 100000 --seed 42 --csv ai/anomaly/data/simu.csv
```

La colonne `label` du CSV vaut `normal`, le nom du scénario pendant l'anomalie, ou `<scénario>_recovery`
pendant le retour au calme (à exclure de l'évaluation des faux positifs).

**Attention** : en même temps que le vrai boîtier, utilisez `--device esp-sim` pour ne pas mélanger les `seq`
(et ajoutez un bloc `esp-sim` dans l'ACL et un compte dans `passwd`).
