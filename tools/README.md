# Outils

| Fichier | Rôle | Responsable |
|---|---|---|
| `setup-poste.ps1` | Installe **tout** le projet sur un poste Windows, le même pour tous (lancé par `installer.cmd` à la racine) | Tous |
| `demo_brain.py` | Démonstration de Sentinel Brain hors ligne sur le simulateur (lancée par `demo.cmd`) | Tous |
| `configurer.py` | Crée `infra/.env` (secrets aléatoires) et les comptes MQTT `infra/mosquitto/passwd`, sans Docker | Poste serveur |
| `doctor.py` | Contrôle un poste ; `--serveur` (ou `verifier-serveur.cmd`) dit s'il peut être le serveur ; `--linux` pour Linux / Raspberry Pi | Tous |
| `serveur-pc.ps1` | PC serveur, en administrateur : pare-feu (443, 8883), NTP pour l'ESP, point d'accès Wi-Fi 2,4 GHz, vérification | Michel, Lisa |
| `demarrer.ps1` | PC serveur : démarre Docker Desktop, la stack et la vision ; `-Arreter` arrête tout | Tous |
| `simulator.py` | Simulateur d'ESP32-S3 au format du contrat (tâche j1) | Jeffrick |
| `bootstrap_github.py` | Crée le dépôt, labels, jalons, issues et Kanban ; `--sync` met à jour les issues et ferme les tâches faites ou retirées | Constantin |
| `repartition.py` | Régénère `docs/repartition.md` depuis le plan du Kanban | Constantin |
| `lock_deps.py` | Régénère les verrous de dépendances (`--check` en CI) | Jeffrick, Constantin |

Outils de la vision (vidéo de démonstration, badges, mesure YOLO) : `ai/vision/tools/`, voir `ai/vision/README.md`.

## Simulateur (`simulator.py`)

Installation : déjà fait par `setup-poste.ps1` (sinon `pip install -r tools/requirements.txt`).

Il publie exactement ce que publiera le boîtier : `telemetry` (2 s, 500 ms quand le gaz monte), `event`,
`health` (30 s) et `status` (dernière volonté `offline`), avec `seq`, `boot_id`, la quantification du DHT11
(pas de 1 °C) et le tampon rejoué après une coupure (`replay: true`).

| Scénario | Ce qui se passe |
| --- | --- |
| `normal` | Régime normal, sans fin (Ctrl+C pour arrêter) |
| `drift` | Température qui monte lentement (+0,6 °C/min, panne de climatisation), gaz stable |
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

# PC serveur, socle (1883 authentifié, compte esp-01)
python tools/simulator.py --host localhost --user esp-01 --password "<mdp>" --scenario all --speed 10

# PC serveur, dès le passage en TLS (8883)
python tools/simulator.py --host localhost --port 8883 --tls --cafile security/certs/ca.crt --user esp-01 --password "<mdp>"

# Depuis un autre poste connecté au point d'accès : --host 192.168.137.1

# Jeu de données étiqueté pour Sentinel Brain (sans broker, instantané, reproductible)
python tools/simulator.py --no-mqtt --scenario all --cooldown 600 --speed 100000 --seed 42 \
    --csv ai/anomaly/data/simu.csv --rx-log ai/anomaly/data/simu_rx.jsonl
```

`--rx-log` écrit tout ce que le broker reçoit (télémétrie, événements, santé, statut, rejeux, tampon renvoyé après
coupure), dans l'ordre d'arrivée : c'est l'entrée de Sentinel Brain dans le notebook. La colonne `label` du CSV vaut `normal`, le nom du scénario pendant l'anomalie, ou `<scénario>_recovery`
pendant le retour au calme (à exclure de l'évaluation des faux positifs).

**Attention** : en même temps que le vrai boîtier, utilisez `--device esp-sim` pour ne pas mélanger les `seq`
(et ajoutez un bloc `esp-sim` dans l'ACL et un compte dans `passwd`).
