# IA — responsable : Jeffrick (binôme vision : Momo)

| Dossier | Contenu | Point d'entrée de l'image |
|---|---|---|
| `vision/` | YOLO personne, zone interdite, flux MJPEG `/video`, alertes | `app/main.py` (FastAPI, port 8001, route `/health`) |
| `anomaly/` | Isolation Forest sur fenêtres glissantes, score, alertes | `app/main.py` (`python -m app.main`) |
| `anomaly/notebooks/` | Exploration, deviendra la section IA du dossier | — |

## Modèles (non versionnés, trop lourds)
- `vision/models/yolov8n_ncnn_model/` : produit par `model.export(format="ncnn", imgsz=320)` **sur le Pi**.
- `anomaly/models/iforest.joblib` : produit par le notebook d'entraînement.

Garder le tableau des mesures de latence (format, taille, ms, FPS) dans `docs/preuves/latence-yolo.md`.
