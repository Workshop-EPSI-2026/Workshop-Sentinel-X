"""Briques d'analyse sans réseau neuronal : zone, intégrité de la caméra, mouvement, badges, présence.

Tout est testable sans webcam ni YOLO (ai/vision/tests).
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

import cv2
import numpy as np


# ------------------------------------------------------------------ zone interdite
def in_polygon(x: float, y: float, poly: tuple[tuple[float, float], ...]) -> bool:
    """Point dans un polygone (lancer de rayon), coordonnées normalisées 0..1."""
    inside, n = False, len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def foot_point(box: tuple[float, float, float, float]) -> tuple[float, float]:
    """Milieu du bas de la boîte : là où la personne touche le sol (plus juste que le centre)."""
    x1, _, x2, y2 = box
    return (x1 + x2) / 2, y2 - 0.02 * (y2 - box[1])


# ------------------------------------------------------------------ intégrité de la caméra
@dataclass
class Integrity:
    brightness: float
    contrast: float
    sharpness: float
    masked: bool
    low_light: bool


def check_integrity(gray: np.ndarray, low_light_threshold: float = 35.0) -> Integrity:
    """Caméra masquée = image presque uniforme (main, papier, cache) ou totalement noire (scotch) ;
    faible luminosité = image sombre mais qui garde ses contrastes relatifs (une pièce dans le noir).
    On compare l'écart-type à la luminosité moyenne (coefficient de variation) : assombrir une scène
    garde ce rapport, la masquer l'écrase. Calculé sur une image réduite : moins de 1 ms."""
    small = cv2.resize(gray, (160, 120), interpolation=cv2.INTER_AREA)
    brightness = float(small.mean())
    contrast = float(small.std())
    sharpness = float(cv2.Laplacian(small, cv2.CV_64F).var())
    variation = contrast / max(brightness, 1.0)
    masked = brightness < 8.0 or (variation < 0.10 and contrast < 10.0)
    return Integrity(brightness, contrast, sharpness, masked, (not masked) and brightness < low_light_threshold)


class Persistence:
    """Un drapeau ne passe à vrai qu'après `seconds` secondes vraies d'affilée (évite les clignotements)."""

    def __init__(self, seconds: float):
        self.seconds, self.since = seconds, None

    def update(self, value: bool, t: float) -> bool:
        if not value:
            self.since = None
            return False
        if self.since is None:
            self.since = t
        return t - self.since >= self.seconds


# ------------------------------------------------------------------ mouvement
class MotionGate:
    """Soustraction de fond (MOG2) sur une image réduite : on ne lance YOLO que s'il se passe quelque chose."""

    def __init__(self, ratio: float = 0.004):
        self.ratio = ratio
        self.bg = cv2.createBackgroundSubtractorMOG2(history=300, varThreshold=32, detectShadows=False)
        self.frames = 0

    def update(self, gray: np.ndarray) -> tuple[bool, float]:
        small = cv2.resize(gray, (160, 120), interpolation=cv2.INTER_AREA)
        mask = self.bg.apply(small)
        self.frames += 1
        moving = float((mask > 0).mean())
        return (self.frames > 5 and moving >= self.ratio), moving


# ------------------------------------------------------------------ badges ArUco
class BadgeReader:
    """Lit les badges ArUco (carrés noir et blanc imprimés, portés par les agents). Pas de biométrie."""

    def __init__(self, dictionary: str = "DICT_4X4_50"):
        d = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, dictionary))
        params = cv2.aruco.DetectorParameters()
        self.detector = cv2.aruco.ArucoDetector(d, params)

    def read(self, gray: np.ndarray) -> list[tuple[int, float, float]]:
        """[(id, x, y)] avec le centre de chaque badge en coordonnées normalisées."""
        corners, ids, _ = self.detector.detectMarkers(gray)
        if ids is None:
            return []
        h, w = gray.shape[:2]
        out = []
        for c, i in zip(corners, ids.flatten(), strict=True):
            cx, cy = c[0].mean(axis=0)
            out.append((int(i), float(cx / w), float(cy / h)))
        return out


def assign_badges(badges: list[tuple[int, float, float]],
                  boxes: dict[int, tuple[float, float, float, float]]) -> dict[int, int]:
    """Associe chaque badge à la plus petite boîte de personne qui contient son centre : {track_id: badge}."""
    res: dict[int, int] = {}
    for bid, x, y in badges:
        inside = [(abs((b[2] - b[0]) * (b[3] - b[1])), tid) for tid, b in boxes.items()
                  if b[0] - 0.02 <= x <= b[2] + 0.02 and b[1] - 0.02 <= y <= b[3] + 0.02]
        if inside:
            res[min(inside)[1]] = bid
    return res


# ------------------------------------------------------------------ présence par personne suivie
@dataclass
class Track:
    track_id: int
    first_seen: float
    last_seen: float
    box: tuple[float, float, float, float]
    conf: float
    in_zone: bool = False
    zone_since: float | None = None
    badge: int | None = None
    badge_seen: float | None = None
    path: deque = field(default_factory=lambda: deque(maxlen=30))

    def dwell(self, t: float) -> float:
        return 0.0 if self.zone_since is None or not self.in_zone else t - self.zone_since


class PresenceTracker:
    """Mémoire par personne suivie : temps passé dans la zone, badge vu une fois et conservé."""

    def __init__(self, zone: tuple[tuple[float, float], ...], forget_s: float = 2.0):
        self.zone, self.forget_s = zone, forget_s
        self.tracks: dict[int, Track] = {}

    def update(self, dets: list[tuple[int, tuple[float, float, float, float], float]], t: float,
               badges: dict[int, int] | None = None) -> list[Track]:
        for tid, box, conf in dets:
            tr = self.tracks.get(tid)
            if tr is None:
                tr = self.tracks[tid] = Track(tid, t, t, box, conf)
            tr.last_seen, tr.box, tr.conf = t, box, conf
            fx, fy = foot_point(box)
            tr.path.append((fx, fy))
            now_in = in_polygon(fx, fy, self.zone)
            if now_in and not tr.in_zone:
                tr.zone_since = t
            tr.in_zone = now_in
        for tid, bid in (badges or {}).items():
            if tid in self.tracks:
                self.tracks[tid].badge, self.tracks[tid].badge_seen = bid, t
        for tid in [k for k, v in self.tracks.items() if t - v.last_seen > self.forget_s]:
            del self.tracks[tid]
        return [tr for tr in self.tracks.values() if tr.last_seen == t]

    def visible(self, t: float, grace_s: float = 1.0) -> list[Track]:
        """Personnes vues récemment : une image ratée ne fait pas « disparaître » quelqu'un."""
        return [tr for tr in self.tracks.values() if t - tr.last_seen <= grace_s]
