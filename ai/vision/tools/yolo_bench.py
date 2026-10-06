"""Mesure de YOLOv8n sur le PC serveur (tâche j2) : PyTorch contre NCNN, plusieurs tailles d'image.

Le modèle pré-entraîné sur COCO détecte déjà les personnes : on ne l'entraîne pas, on choisit le format et la
taille les plus rapides sans perte de détection, puis on installe ce modèle pour le service vision.

Usage, depuis ai/vision avec l'environnement .venv (créé par run-windows.ps1) :
    .venv\\Scripts\\python tools\\yolo_bench.py                      # webcam 0, 200 images
    .venv\\Scripts\\python tools\\yolo_bench.py --source photos\\     # dossier d'images ou fichier vidéo
    .venv\\Scripts\\python tools\\yolo_bench.py --install 320         # installe le modèle NCNN 320 px

Sorties : docs/preuves/latence-yolo.md (tableau pour le jury), docs/preuves/yolo/*.jpg (images annotées),
ai/vision/models/yolov8n_ncnn_model (modèle utilisé par le service, VISION_MODEL dans infra/.env).
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import platform
import shutil
import statistics
import sys
import time
from pathlib import Path

import cv2
from ultralytics import YOLO

VISION_DIR = Path(__file__).resolve().parents[1]
REPO = VISION_DIR.parents[1]
MODELS = VISION_DIR / "models"
PROOFS = REPO / "docs" / "preuves"
PERSON = 0  # classe « person » de COCO
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def load_frames(source: str, count: int) -> tuple[list, str]:
    """Images de test : webcam (index), dossier d'images ou fichier vidéo."""
    frames = []
    if source.isdigit():
        cap = cv2.VideoCapture(int(source), cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        if not cap.isOpened():
            sys.exit(f"Webcam {source} introuvable : vérifier le branchement, ou passer --source <dossier>.")
        for _ in range(10):  # laisser l'exposition automatique se stabiliser
            cap.read()
        while len(frames) < count:
            ok, frame = cap.read()
            if not ok:
                break
            frames.append(frame)
        cap.release()
        label = f"webcam {source}, 640×480, {len(frames)} images"
    else:
        path = Path(source)
        if path.is_dir():
            files = sorted(p for p in path.iterdir() if p.suffix.lower() in IMAGE_EXT)
            frames = [img for img in (cv2.imread(str(p)) for p in files) if img is not None]
            label = f"dossier {path.name}, {len(frames)} images"
        elif path.is_file():
            cap = cv2.VideoCapture(str(path))
            while len(frames) < count:
                ok, frame = cap.read()
                if not ok:
                    break
                frames.append(frame)
            cap.release()
            label = f"vidéo {path.name}, {len(frames)} images"
        else:
            sys.exit(f"Source introuvable : {source}")
    if not frames:
        sys.exit("Aucune image lue.")
    # Moins d'images que demandé (petit dossier) : on les repasse pour stabiliser la mesure
    while len(frames) < count:
        frames.extend(frames[: count - len(frames)])
    return frames[:count], label


def ncnn_model(size: int) -> Path:
    """Exporte (une fois) le modèle NCNN à cette taille ; la taille d'entrée est figée à l'export."""
    target = MODELS / f"yolov8n_ncnn_{size}"
    if not (target / "model.ncnn.param").exists():
        # Export dans un dossier de travail : il produit toujours « yolov8n_ncnn_model », le nom du modèle installé
        work = MODELS / "_export"
        work.mkdir(exist_ok=True)
        shutil.copy2(MODELS / "yolov8n.pt", work / "yolov8n.pt")
        exported = Path(YOLO(str(work / "yolov8n.pt")).export(format="ncnn", imgsz=size))
        if target.exists():
            shutil.rmtree(target)
        shutil.move(str(exported), target)
        shutil.rmtree(work, ignore_errors=True)
    return target


def measure(model: YOLO, frames: list, size: int, conf: float) -> dict:
    for frame in frames[:10]:  # chauffe : allocation mémoire et premiers appels exclus de la mesure
        model.predict(frame, imgsz=size, classes=[PERSON], conf=conf, verbose=False)
    times, persons, sample = [], [], None
    for frame in frames:
        t0 = time.perf_counter()
        result = model.predict(frame, imgsz=size, classes=[PERSON], conf=conf, verbose=False)[0]
        times.append((time.perf_counter() - t0) * 1000)  # prétraitement + inférence + post-traitement
        persons.append(len(result.boxes))
        if sample is None or len(result.boxes) > len(sample.boxes):
            sample = result
    times.sort()
    return {
        "median_ms": statistics.median(times),
        "p95_ms": times[int(len(times) * 0.95) - 1],
        "fps": 1000 / statistics.mean(times),
        "persons": statistics.mean(persons),
        "frames_with_person": sum(1 for p in persons if p) / len(persons),
        "sample": sample,
    }


def machine() -> str:
    cpu = platform.processor() or platform.machine()
    return f"{platform.node()} · {cpu} · {os.cpu_count()} cœurs logiques · {platform.system()} {platform.release()}"


def write_report(rows: list[dict], source_label: str, conf: float) -> Path:
    PROOFS.mkdir(parents=True, exist_ok=True)
    ref = next((r for r in rows if r["format"] == "PyTorch"), rows[0])
    lines = [
        "# Latence YOLO sur le PC serveur (tâche j2)",
        "",
        f"Mesuré le {dt.datetime.now():%d/%m/%Y à %H:%M} avec `ai/vision/tools/yolo_bench.py`.",
        "",
        f"- Machine : {machine()}",
        f"- Modèle : YOLOv8n pré-entraîné sur COCO, classe personne uniquement, confiance {conf}",
        f"- Images : {source_label}",
        "- Temps de bout en bout par image : prétraitement, inférence et post-traitement, après 10 images de chauffe",
        "",
        "| Format | Taille | Médiane (ms) | 95e centile (ms) | Images / s | Personnes / image | Images avec personne | Écart de détection |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        gap = r["persons"] - ref["persons"] if ref["size"] == r["size"] else None
        lines.append(
            f"| {r['format']} | {r['size']} px | {r['median_ms']:.1f} | {r['p95_ms']:.1f} | {r['fps']:.1f} | "
            f"{r['persons']:.2f} | {r['frames_with_person']:.0%} | {'—' if gap is None else f'{gap:+.2f}'} |"
        )
    best = min(rows, key=lambda r: r["median_ms"])
    lines += [
        "",
        "Écart de détection : différence de personnes par image avec PyTorch à la même taille (0 = export sans perte).",
        "",
        f"**Configuration la plus rapide** : {best['format']} {best['size']} px, {best['median_ms']:.1f} ms médians "
        f"({best['fps']:.1f} images/s). Critère du go / no-go de mardi : moins de 100 ms.",
        "",
        "Images annotées : `docs/preuves/yolo/`.",
        "",
    ]
    report = PROOFS / "latence-yolo.md"
    report.write_text("\n".join(lines), encoding="utf-8")
    return report


def install(size: int) -> Path:
    """Copie le modèle NCNN choisi là où le service vision le lit (VISION_MODEL=yolov8n_ncnn_model)."""
    src = ncnn_model(size)
    dst = MODELS / "yolov8n_ncnn_model"
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    return dst


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source", default="0", help="index de webcam, dossier d'images ou fichier vidéo (défaut : 0)")
    p.add_argument("--frames", type=int, default=200, help="images mesurées par configuration (défaut : 200)")
    p.add_argument("--sizes", type=int, nargs="+", default=[320, 640], help="tailles d'image (défaut : 320 640)")
    p.add_argument("--conf", type=float, default=0.5, help="confiance minimale, comme vision.confidence (défaut : 0.5)")
    p.add_argument("--install", type=int, metavar="TAILLE", help="installer le modèle NCNN de cette taille, puis quitter")
    args = p.parse_args()

    MODELS.mkdir(exist_ok=True)
    os.chdir(MODELS)  # le premier lancement télécharge yolov8n.pt ici (ignoré par Git)
    if not (MODELS / "yolov8n.pt").exists():
        YOLO("yolov8n.pt")

    if args.install:
        print(f"Modèle installé : {install(args.install)}")
        print(f"Vérifier que vision.imgsz vaut {args.install} dans le profil de site (config/).")
        return

    frames, source_label = load_frames(args.source, args.frames)
    print(f"Images : {source_label}")
    samples = PROOFS / "yolo"
    samples.mkdir(parents=True, exist_ok=True)

    rows = []
    for size in args.sizes:
        for fmt, model in (("PyTorch", YOLO(str(MODELS / "yolov8n.pt"))), ("NCNN", YOLO(str(ncnn_model(size)), task="detect"))):
            print(f"  {fmt} {size} px…", end=" ", flush=True)
            r = measure(model, frames, size, args.conf)
            cv2.imwrite(str(samples / f"{fmt.lower()}-{size}.jpg"), r.pop("sample").plot())
            rows.append({"format": fmt, "size": size, **r})
            print(f"{r['median_ms']:.1f} ms, {r['fps']:.1f} images/s, {r['persons']:.2f} personne(s)/image")

    report = write_report(rows, source_label, args.conf)
    best = min((r for r in rows if r["format"] == "NCNN"), key=lambda r: r["median_ms"])
    print(f"\nTableau : {report}")
    print(f"Pour installer le modèle retenu : .venv\\Scripts\\python tools\\yolo_bench.py --install {best['size']}")


if __name__ == "__main__":
    main()
