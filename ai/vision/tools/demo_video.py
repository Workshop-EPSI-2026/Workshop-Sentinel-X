#!/usr/bin/env python3
"""Fabrique une vidéo de démonstration (sans webcam) : agent badgé, intrus qui s'attarde, caméra masquée, obscurité.

    python tools/demo_video.py                    # -> ai/vision/data/demo.mp4 (52 s, 640x480, 10 img/s)
    python -m app.main --source data/demo.mp4 --no-mqtt

Sert aux tests de bout en bout, aux répétitions et au plan B de la démo si la webcam lâche.
Les personnes viennent des images d'exemple fournies avec Ultralytics (bus.jpg) ; le badge est un marqueur
ArUco DICT_4X4_50 (le même que ceux imprimés par tools/badges.py).
"""
from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np

W, H, FPS = 640, 480, 10
VISION = Path(__file__).resolve().parents[1]
# Personnes de bus.jpg (boîtes en pixels de l'image d'origine 810x1080)
AGENT_BOX, INTRUDER_BOX = (49, 399, 245, 903), (669, 392, 810, 877)
# Chronologie (secondes) : ce que la vidéo montre et ce que la vision doit en conclure
TIMELINE = [
    (0, 4, "vide", "aucune personne"),
    (4, 12, "agent", "agent badgé 7 qui traverse la zone"),
    (12, 15, "vide", "aucune personne"),
    (15, 40, "intrus", "intrus sans badge qui entre dans la zone et s'attarde (rôdeur après 20 s)"),
    (40, 44, "masque", "caméra masquée"),
    (44, 48, "sombre", "pièce dans le noir"),
    (48, 52, "vide", "retour au calme"),
]


def background(rng: np.random.Generator) -> np.ndarray:
    """Un local technique stylisé : sol, mur, armoire, avec un peu de texture."""
    img = np.full((H, W, 3), (150, 160, 165), np.uint8)
    img[300:] = (95, 100, 105)                                  # sol
    cv2.rectangle(img, (440, 90), (600, 300), (70, 80, 90), -1)  # armoire électrique
    cv2.rectangle(img, (455, 105), (585, 285), (110, 120, 130), 2)
    cv2.rectangle(img, (40, 120), (160, 220), (120, 140, 150), -1)  # tableau
    noise = rng.normal(0, 4, img.shape)
    return np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)


def badge_image(badge_id: int, size: int = 40) -> np.ndarray:
    d = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    m = cv2.aruco.generateImageMarker(d, badge_id, size)
    m = cv2.copyMakeBorder(m, 6, 6, 6, 6, cv2.BORDER_CONSTANT, value=255)
    return cv2.cvtColor(m, cv2.COLOR_GRAY2BGR)


def person(src: np.ndarray, box, height: int, badge: int | None) -> np.ndarray:
    x1, y1, x2, y2 = box
    crop = src[y1:y2, x1:x2]
    w = int(crop.shape[1] * height / crop.shape[0])
    crop = cv2.resize(crop, (w, height), interpolation=cv2.INTER_AREA)
    if badge is not None:                                        # badge porté sur la poitrine
        b = badge_image(badge, max(28, height // 7))
        y, x = int(height * 0.28), (w - b.shape[1]) // 2
        crop[y:y + b.shape[0], x:x + b.shape[1]] = b
    return crop


def paste(img: np.ndarray, sprite: np.ndarray, cx: int, bottom: int) -> None:
    h, w = sprite.shape[:2]
    x0, y0 = max(0, cx - w // 2), max(0, bottom - h)
    x1, y1 = min(W, x0 + w), min(H, y0 + h)
    img[y0:y1, x0:x1] = sprite[: y1 - y0, : x1 - x0]


def frame_at(t: float, bg: np.ndarray, src: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    phase = next(p for a, b, p, _ in TIMELINE if a <= t < b)
    img = bg.copy()
    if phase == "agent":                                         # traverse de gauche à droite
        u = (t - 4) / 8
        paste(img, person(src, AGENT_BOX, 300, badge=7), int(60 + u * 520), 430)
    elif phase == "intrus":                                      # entre puis reste dans la zone
        u = min(1.0, (t - 15) / 4)
        paste(img, person(src, INTRUDER_BOX, 300, badge=None), int(600 - u * 290), 440)
    elif phase == "masque":                                      # main sur l'objectif
        img[:] = 18
    elif phase == "sombre":
        img = (img * 0.12).astype(np.uint8)
    noise = rng.normal(0, 1.5, img.shape)                        # bruit de capteur : jamais deux images identiques
    return np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--output", default=str(VISION / "data" / "demo.mp4"))
    a = ap.parse_args(argv)
    import ultralytics
    src = cv2.imread(str(Path(ultralytics.__file__).parent / "assets" / "bus.jpg"))
    rng = np.random.default_rng(7)
    bg = background(rng)
    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    vw = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))
    for i in range(int(TIMELINE[-1][1] * FPS)):
        vw.write(frame_at(i / FPS, bg, src, rng))
    vw.release()
    print(f"vidéo écrite : {out} ({TIMELINE[-1][1]} s)")
    for a_, b, _, what in TIMELINE:
        print(f"  {a_:>2}-{b:<2} s  {what}")


if __name__ == "__main__":
    main()
