#!/usr/bin/env python3
"""Reconnaissance des visages autorisés : modèles, enrôlement, contrôle de qualité.

    python ai/vision/tools/visages.py modeles                 # télécharge YuNet + SFace dans ai/vision/models
    python ai/vision/tools/visages.py enroler C:\\photos       # un sous-dossier par personne : C:\\photos\\Michel\\*.jpg
    python ai/vision/tools/visages.py tester                  # chaque photo reconnue sans elle-même (fiabilité)
    python ai/vision/tools/visages.py oublier Michel          # retire une personne de la galerie

Seuls des vecteurs de 128 nombres sont gardés (ai/vision/data/visages.npz, ignoré par Git), jamais les photos.
Uniquement des personnes qui ont donné leur accord ; puis les déclarer dans le profil de site
(vision.authorized_faces : nom, horaires), comme les badges.
"""
from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

import cv2
import numpy as np

VISION = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(VISION))
from app.faces import (  # noqa: E402
    DEFAULT_MARGIN,
    DEFAULT_THRESHOLD,
    DETECTOR_FILE,
    RECOGNIZER_FILE,
    FaceEngine,
    Gallery,
)

MODELS = VISION / "models"
GALLERY = VISION / "data" / "visages.npz"
ZOO = "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models"
URLS = {DETECTOR_FILE: f"{ZOO}/face_detection_yunet/{DETECTOR_FILE}",
        RECOGNIZER_FILE: f"{ZOO}/face_recognition_sface/{RECOGNIZER_FILE}"}
IMAGES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
VIDEOS = {".mp4", ".mov", ".avi", ".mkv"}


def modeles(_: argparse.Namespace) -> None:
    MODELS.mkdir(parents=True, exist_ok=True)
    for name, url in URLS.items():
        dest = MODELS / name
        if dest.exists() and dest.stat().st_size > 100_000:
            print(f"[OK] {name} déjà présent")
            continue
        print(f"Téléchargement de {name}...")
        urllib.request.urlretrieve(url, dest)
        print(f"[OK] {name} ({dest.stat().st_size // 1024} Ko)")


def _frames(path: Path, every_s: float = 0.5, max_frames: int = 30):
    if path.suffix.lower() in IMAGES:
        try:
            img = cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_COLOR)   # chemins accentués (Windows)
        except OSError:
            img = None
        if img is not None:
            yield path.name, img
        return
    cap = cv2.VideoCapture(str(path))
    step = max(1, int((cap.get(cv2.CAP_PROP_FPS) or 30) * every_s))
    i = n = 0
    while n < max_frames:
        ok, img = cap.read()
        if not ok:
            break
        if i % step == 0:
            n += 1
            yield f"{path.name}#{i}", img
        i += 1
    cap.release()


def _fit(img: np.ndarray, max_side: int = 960) -> np.ndarray:
    h, w = img.shape[:2]
    k = max_side / max(h, w)
    return cv2.resize(img, (int(w * k), int(h * k)), interpolation=cv2.INTER_AREA) if k < 1 else img


def enroler(a: argparse.Namespace) -> None:
    root = Path(a.dossier)
    people = sorted(p for p in root.iterdir() if p.is_dir())
    if not people:
        sys.exit(f"Aucun sous-dossier dans {root} : un dossier par personne (Michel, Jeffrick...)")
    engine = FaceEngine(MODELS)
    old = Gallery.load(GALLERY) if GALLERY.exists() and not a.remplacer else None
    names, feats, labels = (list(old.names), list(old.feats), list(old.labels)) if old else ([], [], [])
    for person in people:
        name = person.name.strip()
        if name in names:                       # nouvel enrôlement : remplace les anciens vecteurs de la personne
            idx = names.index(name)
            keep = [i for i, lab in enumerate(labels) if lab != idx]
            feats, labels = [feats[i] for i in keep], [labels[i] for i in keep]
        else:
            names.append(name)
            idx = len(names) - 1
        ok = refused = 0
        for f in sorted(person.rglob("*")):
            if f.suffix.lower() not in IMAGES | VIDEOS:
                continue
            for _, img in _frames(f):
                img = _fit(img)
                faces = engine.detect(img)
                if len(faces) != 1 or not engine.frontal(faces[0]):   # aucun, plusieurs, ou de profil
                    refused += 1
                    continue
                feats.append(engine.feature(img, faces[0]))
                labels.append(idx)
                ok += 1
        print(f"{name:12s} {ok:3d} images retenues, {refused} écartées (visage absent, de profil ou plusieurs visages)")
        if ok < 5:
            print(f"   !! {name} : moins de 5 images, reconnaissance peu fiable : ajouter des photos de face")
    if not feats:
        sys.exit("Aucun visage retenu.")
    used = sorted(set(labels))
    remap = {old_i: new_i for new_i, old_i in enumerate(used)}
    g = Gallery([names[i] for i in used], np.array(feats), np.array([remap[lab] for lab in labels]))
    g.save(GALLERY)
    print(f"[OK] galerie {GALLERY} : {', '.join(g.names)} ({len(g.feats)} vecteurs, aucune photo)")
    tester(a)


def tester(a: argparse.Namespace) -> None:
    """Validation croisée : chaque vecteur est comparé à la galerie privée de lui-même."""
    g = Gallery.load(GALLERY)
    th = getattr(a, "seuil", None) or DEFAULT_THRESHOLD
    good = unknown = wrong = 0
    lowest: dict[str, float] = {}
    for i, f in enumerate(g.feats):
        truth = g.names[g.labels[i]]
        name, s = g.match(f, th, DEFAULT_MARGIN, exclude=i)
        lowest[truth] = min(lowest.get(truth, 1.0), s)
        if name == truth:
            good += 1
        elif name is None:
            unknown += 1
        else:
            wrong += 1
            print(f"   !! une image de {truth} prise pour {name} ({s:.2f})")
    n = len(g.feats)
    print(f"Contrôle (seuil {th}) : {good}/{n} reconnues, {unknown} non reconnues, {wrong} confondues")
    if len(g.names) > 1:
        cross = max(g.scores(f).get(other, -1) for i, f in enumerate(g.feats)
                    for other in g.names if other != g.names[g.labels[i]])
        print(f"Similarité la plus forte entre deux personnes différentes : {cross:.2f} (doit rester sous {th})")


def oublier(a: argparse.Namespace) -> None:
    g = Gallery.load(GALLERY)
    if a.nom not in g.names:
        sys.exit(f"{a.nom} n'est pas dans la galerie ({', '.join(g.names)})")
    idx = g.names.index(a.nom)
    keep = g.labels != idx
    if not keep.any():
        GALLERY.unlink()
        print(f"[OK] {a.nom} oublié : galerie supprimée")
        return
    names = [n for i, n in enumerate(g.names) if i != idx]
    labels = np.array([lab - (lab > idx) for lab in g.labels[keep]])
    Gallery(names, g.feats[keep], labels).save(GALLERY)
    print(f"[OK] {a.nom} oublié (reste : {', '.join(names)})")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("modeles").set_defaults(fn=modeles)
    e = sub.add_parser("enroler")
    e.add_argument("dossier")
    e.add_argument("--remplacer", action="store_true", help="repartir d'une galerie vide")
    e.set_defaults(fn=enroler)
    t = sub.add_parser("tester")
    t.add_argument("--seuil", type=float)
    t.set_defaults(fn=tester)
    o = sub.add_parser("oublier")
    o.add_argument("nom")
    o.set_defaults(fn=oublier)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
