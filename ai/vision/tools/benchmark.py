#!/usr/bin/env python3
"""Mesure YOLOv8n sur la machine (tâche j2) et écrit le tableau dans docs/preuves/latence-yolo.md.

    python tools/benchmark.py                     # PyTorch, 320 et 640 px
    python tools/benchmark.py --ncnn              # + export NCNN (format du Raspberry Pi ; télécharge pnnx une fois)

Image de test : bus.jpg (fournie avec Ultralytics), 5 passages d'échauffement puis 50 mesurés.
Critère : moins de 100 ms par image à 320 px (au moins 10 images/s pour le suivi).
"""
from __future__ import annotations

import argparse
import os
import platform
import statistics
import time
from datetime import datetime
from pathlib import Path

import cv2

VISION = Path(__file__).resolve().parents[1]
ROOT = VISION.parents[1]


def cpu_name() -> str:
    name = platform.processor() or platform.machine()
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith(("model name", "Model")):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return name


def measure(model_path: str, imgsz: int, img, runs: int) -> dict:
    os.environ.setdefault("YOLO_OFFLINE", "true")         # pas de statistiques d'usage envoyées
    from ultralytics import YOLO
    m = YOLO(model_path, task="detect")
    for _ in range(5):
        m(img, imgsz=imgsz, classes=[0], verbose=False)
    ms = []
    for _ in range(runs):
        t0 = time.perf_counter()
        r = m(img, imgsz=imgsz, classes=[0], verbose=False)
        ms.append((time.perf_counter() - t0) * 1000)
    ms.sort()
    return {"format": "NCNN" if "ncnn" in model_path else "PyTorch", "imgsz": imgsz,
            "ms": statistics.mean(ms), "p95": ms[int(0.95 * len(ms)) - 1], "fps": 1000 / statistics.mean(ms),
            "persons": len(r[0].boxes)}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default=str(VISION / "models" / "yolov8n.pt"))
    ap.add_argument("--ncnn", action="store_true", help="exporter et mesurer aussi le format NCNN")
    ap.add_argument("--runs", type=int, default=50)
    ap.add_argument("--machine", default=platform.node(), help="nom affiché dans le tableau")
    ap.add_argument("--out", default=str(ROOT / "docs" / "preuves" / "latence-yolo.md"))
    a = ap.parse_args(argv)
    import ultralytics
    img = cv2.imread(str(Path(ultralytics.__file__).parent / "assets" / "bus.jpg"))
    exported = []
    if a.ncnn:                                             # export d'abord : il a besoin d'Internet (pnnx)
        from ultralytics import YOLO
        exported = [(str(YOLO(a.model).export(format="ncnn", imgsz=s)), s) for s in (320, 640)]
    rows = [measure(a.model, s, img, a.runs) for s in (320, 640)]
    rows += [measure(path, s, img, a.runs) for path, s in exported]
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    head = "" if out.exists() else ("# Latence de YOLOv8n (tâche j2)\n\nImage bus.jpg, classe personne, 50 mesures "
                                    "après 5 passages d'échauffement. Objectif : < 100 ms à 320 px.\n\n"
                                    "| Date | Machine | Processeur | Format | Taille | Moyenne (ms) | p95 (ms) | "
                                    "Images/s | Personnes |\n|---|---|---|---|---|---|---|---|---|\n")
    lines = [f"| {datetime.now():%Y-%m-%d %H:%M} | {a.machine} | {cpu_name()} | {r['format']} | {r['imgsz']} | "
             f"{r['ms']:.0f} | {r['p95']:.0f} | {r['fps']:.1f} | {r['persons']} |" for r in rows]
    with out.open("a", encoding="utf-8") as f:
        f.write(head + "\n".join(lines) + "\n")
    print(head + "\n".join(lines))
    print(f"\nTableau complété : {out}")


if __name__ == "__main__":
    main()
