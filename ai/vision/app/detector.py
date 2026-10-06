"""Détection et suivi de personnes : YOLOv8n (Ultralytics) + ByteTrack.

Sur le PC : modèle PyTorch yolov8n.pt (téléchargé automatiquement dans ai/vision/models au premier lancement).
Sur un Raspberry Pi : export NCNN (yolov8n_ncnn_model), 2 à 3 fois plus rapide sur processeur ARM.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol

import numpy as np

Detection = tuple[int, tuple[float, float, float, float], float]   # (id de suivi, boîte normalisée, confiance)


class Detector(Protocol):
    def track(self, frame: np.ndarray) -> list[Detection]: ...


class YoloPersonDetector:
    PERSON = 0

    def __init__(self, model_path: str, imgsz: int = 320, conf: float = 0.5):
        if Path(model_path).exists():
            # modèle présent : aucun accès Internet (statistiques d'usage, mises à jour automatiques)
            os.environ.setdefault("YOLO_OFFLINE", "true")
        from ultralytics import YOLO  # import tardif : les tests sans YOLO restent rapides

        Path(model_path).parent.mkdir(parents=True, exist_ok=True)
        self.model = YOLO(model_path, task="detect")
        self.imgsz, self.conf = imgsz, conf

    def track(self, frame: np.ndarray) -> list[Detection]:
        r = self.model.track(frame, persist=True, classes=[self.PERSON], imgsz=self.imgsz, conf=self.conf,
                             tracker="bytetrack.yaml", verbose=False)[0]
        if r.boxes is None or len(r.boxes) == 0:
            return []
        boxes = r.boxes.xyxyn.cpu().numpy()
        confs = r.boxes.conf.cpu().numpy()
        if r.boxes.id is None:              # premières images d'une piste : pas encore d'identifiant
            return []
        ids = r.boxes.id.cpu().numpy().astype(int)
        return [(int(i), tuple(float(v) for v in b), float(c)) for i, b, c in zip(ids, boxes, confs, strict=True)]
