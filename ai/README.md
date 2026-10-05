# IA — Jeffrick (binôme vision : Momo ; détection cyber : Lisa)

| Dossier | Service | Point d'entrée de l'image |
|---|---|---|
| `vision/` | YOLOv8n NCNN, suivi, zone interdite, temps de présence, caméra masquée, faible luminosité, `/video` | `app/main.py` (FastAPI, port 8001, `/health`) |
| `anomaly/` | **Sentinel Brain** : détection multicouche, fusion, incidents expliqués, score en direct | `app/main.py` (`python -m app.main`) |
| `anomaly/notebooks/` | Exploration et validation (section IA du dossier) | — |

## Sentinel Brain en quatre couches
1. **Qualité des données** : plausibilité (DHT11 0-50 °C, 20-90 %), capteur figé, trous de `seq`, rejeu (`boot_id` + `seq`).
2. **Par capteur** : ligne de base EWMA, écart robuste (médiane, MAD), **CUSUM** pour les dérives lentes. Température lissée (pas de 1 °C du DHT11).
3. **Multivariée** : Isolation Forest sur fenêtres de 60 s (température lissée et pente, humidité, ratio gaz et pente, corrélation température-gaz, PIR/min, RSSI).
4. **Prévision** : lissage exponentiel double (Holt) → `eta_min` avant le niveau critique.

Puis **fusion** : scores environnement / physique / cyber (0-100), Sentinel Score global, règles de corrélation
(intrusion confirmée, sabotage, risque incendie, fuite de gaz, brouillage, attaque cyber, capteur défaillant),
explication des facteurs dominants, cycle de vie avec délai minimal entre deux notifications.

**Adaptation** : apprentissage 10 min au démarrage, réentraînement toutes les 30 min sur fenêtres sans incident,
sensibilités lues dans le profil de site (`sentinel/site/config`). Modèles persistés dans le volume `brain-models`.

## Indicateurs à mesurer pour le jury
Minutes d'anticipation avant le seuil · faux positifs sur 1 h de régime normal · latence de bout en bout · FPS sur Pi 5 et Pi 4.
Tableau YOLO (format, taille, ms, FPS) dans `docs/preuves/latence-yolo.md`.
