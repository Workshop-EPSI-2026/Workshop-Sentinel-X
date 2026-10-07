# Sentinel Brain (`ai/anomaly`)

Moteur de détection multicouche de Sentinel-X. Responsable : Jeffrick (tâches j3, je3, je5).

| Chemin | Rôle |
| --- | --- |
| `brain/quality.py` | Couche 1 : schéma, plausibilité, capteur figé, `seq` / `boot_id` (rejeu), horodatage |
| `brain/detectors.py` | Couches 2 et 4 : CUSUM robuste décorrélé, vitesse de montée, Holt à pas variable, test de Poisson (PIR) |
| `brain/multivariate.py` | Couche 3 : Isolation Forest sur fenêtres de 60 s, réentraîné sur le régime sain |
| `brain/site.py` | Règles de site : badges autorisés et horaires, état des caméras, accès refusés du broker |
| `brain/engine.py` | Fusion en 3 domaines (capteurs + vision), Sentinel Score, règles de corrélation, incidents expliqués |
| `brain/config.py` | Lecture du profil de site + réglages calibrés (`CALIBRATION`) |
| `app/main.py` | **Service** (tâche je3) : MQTT ↔ Brain ↔ API, journal de Mosquitto, rechargement du profil à chaud |
| `notebooks/01-prototype.ipynb` | Prototype j3 : données, calibration, démonstration de chaque couche, évaluation |
| `tests/test_brain.py` | Tests : couches, scénarios simulés, fusion vision / badges / horaires, accès refusés |
| `data/` | Jeux simulés, **non versionnés** : le notebook les régénère (graines fixes) |

## Le service en production

Il tourne dans le conteneur `anomaly` (profil `ai`). Entrées : `sentinel/+/telemetry|event|health|status|vision`,
`sentinel/site/config`, et le journal de Mosquitto (volume partagé en lecture seule). Sorties : `sentinel/brain/score`,
`sentinel/brain/alert` et `POST /api/v1/alerts` (file d'attente : si l'API est absente, les alertes attendent).
Santé : `/tmp/brain.alive` touché toutes les 5 s (contrôle de santé Docker).

```powershell
# Logs en direct sur le PC serveur
docker logs -f snx-anomaly
# Hors Docker, pour déboguer (broker du socle sur 1883, depuis ai\anomaly)
python -m app.main --env ..\..\infra\.env --host localhost --port 1883 --profile ..\..\config\site.example.yml
```

## Ce que Brain détecte

| Domaine | Incidents | Comment |
| --- | --- | --- |
| Environnement | fuite de gaz, risque incendie, dérive thermique, combinaison inhabituelle | 4 couches, prévision `eta_min` |
| Physique | intrusion confirmée (vision + PIR < 5 s), intrusion présumée, rôdeur, présence autorisée, présence à vérifier (badge hors horaires), intrus accompagné, sabotage (boîtier ouvert, caméra masquée ou muette après une détection) | Vision + PIR + effraction + badges + horaires |
| Cyber | rejeu (boîtier ou caméra), horodatage falsifié, rafale d'accès MQTT refusés (avec l'adresse IP), brouillage Wi-Fi | Couche 1, journal de Mosquitto, RSSI |
| Maintenance | capteur figé ou impossible, caméra dégradée (sombre, hors ligne) | Couche 1, vision |

Quand la caméra est masquée, sombre ou hors ligne, le PIR devient plus sensible et une intrusion PIR seule est signalée
(« caméra aveugle, le PIR fait foi ») ; quand la caméra voit la scène, c'est elle qui porte l'incident.

## Résultats du prototype (données simulées)

| Scénario | Détection Brain | Seuil brut | Gain |
| --- | --- | --- | --- |
| Fuite de gaz | 36 s, avec `eta_min` ; critique à 76 s (« critique dans 3,0 min », réel 2,8) | 95 s (ratio 1,3) | ≈ 1 min ; 2 min 47 avant le seuil critique |
| Incendie | 20 s (gaz), requalifié risque incendie critique à 50 s | 96 s | ≈ 1 min 15 |
| Dérive thermique | 4 min 28 | jamais (25 °C < 35 °C) | détecté sans seuil |
| Intrusion · effraction · rejeu · brouillage | 12 s · immédiat · immédiat · 30 s | — | — |
| Fausses alarmes | 0 sur 2 h de régime normal du jeu d'évaluation ; 1 avertissement (brouillage) sur 24 h inédites | | |

Validé de bout en bout (Mosquitto TLS, simulateur, vidéo de démonstration) : agent badgé → présence autorisée ;
intrus + PIR → intrusion confirmée en 3 s ; 20 s dans la zone → rôdeur ; main sur l'objectif → sabotage ;
5 mauvais mots de passe → attaque cyber avec l'adresse IP. Coût : environ 1 ms par message.

## Commandes (racine du dépôt, `.venv` activé)

```powershell
jupyter lab ai/anomaly/notebooks/01-prototype.ipynb      # prototype, ~3 min pour tout exécuter
python -m unittest discover -s ai/anomaly/tests -v       # tests (aussi lancés par la CI)
python tools/simulator.py --no-mqtt --scenario all --cooldown 600 --speed 100000 --seed 42 `
    --csv ai/anomaly/data/simu.csv --rx-log ai/anomaly/data/simu_rx.jsonl
```

**À refaire sur données réelles** : la section 3 du notebook (calibration) avec quelques heures exportées de la base
(table `telemetry`, commande d'export dans `infra/postgres/init/README.md`), puis reporter les valeurs dans `CALIBRATION`.
