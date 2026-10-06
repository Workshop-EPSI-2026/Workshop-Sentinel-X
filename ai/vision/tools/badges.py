#!/usr/bin/env python3
"""Imprime les badges des agents autorisés : marqueurs ArUco DICT_4X4_50 (aucune donnée biométrique).

    python tools/badges.py 7 12              # -> ai/vision/data/badges/badge-07.png, badge-12.png
    python tools/badges.py 7 --cm 6          # taille imprimée (défaut 6 cm, lisible jusqu'à ~3 m en 640x480)

Puis déclarer chaque badge dans config/site.example.yml (vision.authorized_badges : id, nom, horaires).
Un badge se photocopie : c'est une « autorisation présumée », croisée avec les horaires et le mode maintenance.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np

VISION = Path(__file__).resolve().parents[1]
DPI = 300


def badge(badge_id: int, cm: float) -> np.ndarray:
    px = int(cm / 2.54 * DPI)
    d = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    marker = cv2.aruco.generateImageMarker(d, badge_id, px)
    quiet = px // 6                                           # marge blanche indispensable à la détection
    img = cv2.copyMakeBorder(marker, quiet, quiet + px // 4, quiet, quiet, cv2.BORDER_CONSTANT, value=255)
    text = f"SENTINEL-X  badge {badge_id:02d}"
    scale = px / 500
    (tw, _), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 2)
    cv2.putText(img, text, ((img.shape[1] - tw) // 2, img.shape[0] - quiet // 2), cv2.FONT_HERSHEY_SIMPLEX,
                scale, 0, 2, cv2.LINE_AA)
    return img


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ids", nargs="+", type=int, help="identifiants de 0 à 49")
    ap.add_argument("--cm", type=float, default=6.0)
    ap.add_argument("-o", "--outdir", default=str(VISION / "data" / "badges"))
    a = ap.parse_args(argv)
    out = Path(a.outdir)
    out.mkdir(parents=True, exist_ok=True)
    for i in a.ids:
        if not 0 <= i < 50:
            raise SystemExit(f"identifiant {i} hors de 0..49 (dictionnaire DICT_4X4_50)")
        path = out / f"badge-{i:02d}.png"
        cv2.imwrite(str(path), badge(i, a.cm))
        print(f"{path}  (imprimer à 100 %, {a.cm:g} cm de côté, {DPI} ppp)")


if __name__ == "__main__":
    main()
