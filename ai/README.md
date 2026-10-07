# IA — Jeffrick (binôme vision : Momo ; détection cyber : Lisa)

Deux modèles, deux services, un seul cerveau qui fusionne :

| Dossier | Service | Où il tourne | Point d'entrée |
|---|---|---|---|
| `vision/` | Mouvement, YOLOv8n + suivi ByteTrack, zone interdite, temps de présence, badges ArUco, caméra masquée / sombre / figée, flux `/video` | **Sur le PC Windows, hors Docker** (webcam) ; conteneur sous Linux / Raspberry Pi | `python -m app.main` (port 8001) |
| `anomaly/` | **Sentinel Brain** : 4 couches sur les capteurs, fusion avec la vision, badges et horaires, accès refusés du broker, incidents expliqués, score en direct | Conteneur `anomaly` (Docker Desktop) | `python -m app.main` |
| `notify/` | **Notifications** : annonce vocale (« Intrus détecté », « Caméra masquée »…) et mail aux propriétaires avec photo, date et heure | **Sur le PC**, hors Docker (haut-parleurs) | `python -m app.main` |

```
webcam ──► vision ──► sentinel/cam-01/vision ─┐
ESP32-S3 ─► sentinel/esp-01/telemetry|event ──┼──► Sentinel Brain ──► POST /api/v1/alerts + sentinel/brain/score
journal Mosquitto (accès refusés) ────────────┘                                  └─► sentinel/brain/alert ──► notifications (voix, mail + photo)
```

La vision **voit** (qui, où, depuis combien de temps, quel badge) ; Brain **décide** (intrusion confirmée par le PIR,
agent autorisé dans ses horaires, rôdeur, sabotage). Aucune reconnaissance faciale : les agents portent un badge ArUco.

## Sentinel Brain en quatre couches
1. **Qualité des données** : plausibilité, capteur figé, `seq` + `boot_id` (rejeu), horodatage falsifié.
2. **Par capteur** : CUSUM décorrélé (dérives lentes) + vitesse de montée (fuite, feu), température lissée.
3. **Multivariée** : Isolation Forest sur fenêtres de 60 s, réentraîné sur le régime sain.
4. **Prévision** : Holt à pas variable → `eta_min` avant le niveau critique.

Puis **fusion** : environnement / physique / cyber (0-100), Sentinel Score, règles de corrélation et cycle de vie des
incidents. Détails et résultats : `anomaly/README.md`, `anomaly/notebooks/01-prototype.ipynb`.

## Indicateurs à présenter au jury
Avance sur les seuils bruts (fuite : 1 min, critique prévu ~3 min avant) · fausses alarmes sur 24 h normales ·
latence YOLO et images/s sur le PC (`vision/tools/benchmark.py` → `docs/preuves/latence-yolo.md`) ·
délai PIR → intrusion confirmée.
