"""Reconnaissance des visages des membres autorisés (liste blanche locale, avec leur accord).

Deux petits réseaux ONNX lus par OpenCV, sans dépendance de plus :
  YuNet  (face_detection_yunet_2023mar.onnx, 230 Ko)  : trouve les visages et 5 points (yeux, nez, bouche)
  SFace  (face_recognition_sface_2021dec.onnx, 37 Mo) : aligne le visage et le résume en 128 nombres
Téléchargement : python ai/vision/tools/visages.py modeles

La galerie (ai/vision/data/visages.npz) ne contient que ces vecteurs, jamais les photos ; elle reste sur le PC
(ignorée par Git) et se refait avec : python ai/vision/tools/visages.py enroler DOSSIER
Un visage reconnu n'est qu'un indice : Brain décide (liste vision.authorized_faces + horaires), comme pour les badges.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger("vision.faces")

DETECTOR_FILE = "face_detection_yunet_2023mar.onnx"
RECOGNIZER_FILE = "face_recognition_sface_2021dec.onnx"
# Seuil cosinus de SFace : 0,363 d'après ses auteurs (LFW) ; plus strict ici, une fausse acceptation laisserait
# passer un intrus alors qu'un refus ne coûte qu'une alerte à vérifier.
DEFAULT_THRESHOLD = 0.45
DEFAULT_MARGIN = 0.05     # le meilleur doit dépasser le deuxième d'au moins autant, sinon : inconnu


@dataclass
class FaceMatch:
    name: str | None          # None : visage vu mais inconnu
    score: float              # similarité cosinus avec la personne la plus proche
    box: tuple[float, float, float, float]   # visage, coordonnées normalisées de l'image entière


class Gallery:
    """Vecteurs de référence par personne. Comparaison : moyenne des 3 meilleures similarités par personne."""

    def __init__(self, names: list[str], feats: np.ndarray, labels: np.ndarray):
        self.names, self.feats, self.labels = names, _normalize(feats.astype(np.float32)), labels.astype(int)

    @classmethod
    def load(cls, path: str | Path) -> Gallery:
        d = np.load(path, allow_pickle=False)
        return cls([str(n) for n in d["names"]], d["feats"], d["labels"])

    def save(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        np.savez(path, names=np.array(self.names), feats=self.feats, labels=self.labels)

    def scores(self, feat: np.ndarray, exclude: int | None = None) -> dict[str, float]:
        sims = self.feats @ _normalize(feat.reshape(1, -1).astype(np.float32))[0]
        out = {}
        for i, name in enumerate(self.names):
            mask = self.labels == i
            if exclude is not None:
                mask[exclude] = False
            s = np.sort(sims[mask])[::-1][:3]
            if s.size:
                out[name] = float(s.mean())
        return out

    def match(self, feat: np.ndarray, threshold: float = DEFAULT_THRESHOLD, margin: float = DEFAULT_MARGIN,
              exclude: int | None = None) -> tuple[str | None, float]:
        sc = sorted(self.scores(feat, exclude).items(), key=lambda kv: kv[1], reverse=True)
        if not sc:
            return None, 0.0
        best, s = sc[0]
        second = sc[1][1] if len(sc) > 1 else -1.0
        return (best if s >= threshold and s - second >= margin else None), s


def _normalize(x: np.ndarray) -> np.ndarray:
    return x / np.maximum(np.linalg.norm(x, axis=1, keepdims=True), 1e-9)


class FaceEngine:
    """Détection (YuNet) + vecteur (SFace)."""

    def __init__(self, models_dir: str | Path, min_face_px: int = 40):
        models_dir = Path(models_dir)
        self.detector = cv2.FaceDetectorYN.create(str(models_dir / DETECTOR_FILE), "", (320, 320), 0.8, 0.3, 50)
        self.recognizer = cv2.FaceRecognizerSF.create(str(models_dir / RECOGNIZER_FILE), "")
        self.min_face_px = min_face_px

    @staticmethod
    def available(models_dir: str | Path) -> bool:
        return all((Path(models_dir) / f).exists() for f in (DETECTOR_FILE, RECOGNIZER_FILE))

    def detect(self, img: np.ndarray) -> np.ndarray:
        """Visages trouvés (une ligne par visage : x, y, l, h, 5 points, score), du plus grand au plus petit."""
        h, w = img.shape[:2]
        self.detector.setInputSize((w, h))
        _, faces = self.detector.detect(img)
        if faces is None:
            return np.empty((0, 15), np.float32)
        faces = faces[(faces[:, 2] >= self.min_face_px) & (faces[:, 3] >= self.min_face_px)]
        return faces[np.argsort(-faces[:, 2] * faces[:, 3])]

    @staticmethod
    def frontal(face: np.ndarray, max_yaw: float = 0.3) -> bool:
        """Visage à peu près de face : le nez reste entre les yeux. De profil, deux personnes différentes se
        ressemblent trop pour SFace (mesuré sur les photos de l'équipe) : on ne compare que des visages de face."""
        eye_r, eye_l, nose = face[4:6], face[6:8], face[8:10]
        dist = float(np.linalg.norm(eye_l - eye_r))
        if dist < 1:
            return False
        mid = (eye_l + eye_r) / 2
        return abs(float(np.dot(nose - mid, (eye_l - eye_r) / dist))) / dist <= max_yaw

    def feature(self, img: np.ndarray, face: np.ndarray) -> np.ndarray:
        aligned = self.recognizer.alignCrop(img, face)
        return self.recognizer.feature(aligned).reshape(-1)

    def largest_feature(self, img: np.ndarray) -> np.ndarray | None:
        faces = self.detect(img)
        return self.feature(img, faces[0]) if len(faces) else None


class FaceIdentifier:
    """Identifie le visage d'une personne suivie par YOLO : on cherche le visage dans le haut de sa boîte."""

    def __init__(self, engine: FaceEngine, gallery: Gallery, threshold: float = DEFAULT_THRESHOLD,
                 margin: float = DEFAULT_MARGIN):
        self.engine, self.gallery, self.threshold, self.margin = engine, gallery, threshold, margin

    def identify(self, frame: np.ndarray, box: tuple[float, float, float, float]) -> FaceMatch | None:
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = box
        bw, bh = x2 - x1, y2 - y1
        # toute la boîte, avec une marge : debout, le visage est en haut ; tout près de la webcam (cas courant),
        # il peut être n'importe où dans la boîte. YuNet cherche partout, le plus grand visage est retenu.
        cx1, cx2 = max(0.0, x1 - 0.1 * bw), min(1.0, x2 + 0.1 * bw)
        cy1, cy2 = max(0.0, y1 - 0.1 * bh), min(1.0, y2)
        X1, Y1, X2, Y2 = int(cx1 * w), int(cy1 * h), int(cx2 * w), int(cy2 * h)
        if X2 - X1 < 40 or Y2 - Y1 < 40:
            return None
        crop = frame[Y1:Y2, X1:X2]
        faces = self.engine.detect(crop)
        if not len(faces):
            return None
        f = faces[0]
        if not self.engine.frontal(f):
            return None                                # de profil : pas d'avis plutôt qu'un avis douteux
        name, score = self.gallery.match(self.engine.feature(crop, f), self.threshold, self.margin)
        fx, fy, fw, fh = (float(v) for v in f[:4])
        return FaceMatch(name, round(score, 3), ((X1 + fx) / w, (Y1 + fy) / h, (X1 + fx + fw) / w, (Y1 + fy + fh) / h))


def load_identifier(models_dir: str | Path, gallery_path: str | Path, threshold: float = DEFAULT_THRESHOLD
                    ) -> FaceIdentifier | None:
    """Identifiant prêt, ou None (modèles ou galerie absents : la vision tourne sans reconnaissance)."""
    if not FaceEngine.available(models_dir):
        log.info("reconnaissance des visages inactive : modèles absents (python ai/vision/tools/visages.py modeles)")
        return None
    if not Path(gallery_path).exists():
        log.info("reconnaissance des visages inactive : pas de galerie %s (visages.py enroler DOSSIER)", gallery_path)
        return None
    g = Gallery.load(gallery_path)
    log.info("reconnaissance des visages active : %s (%d vecteurs)", ", ".join(g.names), len(g.feats))
    return FaceIdentifier(FaceEngine(models_dir), g, threshold)


class IdentityVotes:
    """Une identité par personne suivie, confirmée après `need` reconnaissances concordantes (une erreur isolée
    ne suffit pas) ; un visage connu vu ensuite comme un autre nom annule la confirmation."""

    def __init__(self, need: int = 2):
        self.need = need
        self.votes: dict[str, int] = {}
        self.name: str | None = None
        self.score: float | None = None

    def add(self, m: FaceMatch) -> None:
        if m.name is None:
            return                                    # visage de profil ou flou : ni pour ni contre
        if self.name is not None and m.name != self.name:
            self.votes, self.name, self.score = {}, None, None
        self.votes[m.name] = self.votes.get(m.name, 0) + 1
        self.score = m.score if self.score is None else max(self.score, m.score)
        if self.votes[m.name] >= self.need:
            self.name = m.name
