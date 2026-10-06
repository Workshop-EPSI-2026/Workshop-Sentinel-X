#!/usr/bin/env python3
"""
Sentinel-X — régénère les fichiers de dépendances verrouillés (versions exactes, toutes plateformes).

    pip install uv
    python tools/lock_deps.py          # régénère tous les requirements.txt
    python tools/lock_deps.py --check  # échoue si un .txt n'est plus à jour (utilisé par la CI)

Source des versions : les fichiers requirements.in (plages). Les requirements.txt sont générés : ne pas
les modifier à la main. Toute mise à jour passe par une Pull Request (voir VERSIONS.md).

Cas de la vision : PyTorch est retiré du verrou et installé en version CPU depuis l'index officiel de
PyTorch (ai/vision/torch-cpu.txt). Sinon, sur le Raspberry Pi (Linux ARM), PyTorch tire des paquets NVIDIA
inutiles et très lourds.
"""
import argparse
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PY = "3.12"
# Seules les versions publiées avant cette date sont retenues : on évite les versions de la veille,
# pas encore éprouvées. Repousser cette date est une décision d'équipe (Pull Request).
EXCLUDE_NEWER = "2026-08-15"
TARGETS = ["tools", "api", "ai/anomaly", "ai/vision", "."]
# nvidia-ml-py (supervision GPU, tiré par Ultralytics) est un petit paquet pur Python : on le garde dans le verrou
TORCH_STACK = re.compile(r"^(torch|torchvision|triton|nvidia-(?!ml-py)[a-z0-9-]+|cuda-[a-z0-9-]+)==", re.I)


def compile_one(src: pathlib.Path) -> str:
    cmd = ["uv", "pip", "compile", str(src.relative_to(ROOT)), "--universal", "--python-version", PY,
           "--no-header", "-q", "--exclude-newer", EXCLUDE_NEWER]
    out = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit(f"Échec de résolution pour {src}:\n{out.stderr}")
    return out.stdout


def strip_torch(lock: str) -> tuple[str, list[str]]:
    """Retire la pile PyTorch du verrou (et ses lignes « # via »), renvoie les versions de torch."""
    kept, pins, skip = [], [], False
    for line in lock.splitlines():
        if TORCH_STACK.match(line):
            name = line.split("==")[0].lower()
            if name in ("torch", "torchvision"):
                pins.append(line.split(" ;")[0].strip())
            skip = True
            continue
        if skip and line.startswith("    "):
            continue
        skip = False
        kept.append(line)
    return "\n".join(kept) + "\n", sorted(set(pins))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    stale = []
    for t in TARGETS:
        d = ROOT / t
        src = d / ("requirements-dev.in" if t == "." else "requirements.in")
        dst = d / ("requirements-dev.txt" if t == "." else "requirements.txt")
        lock = compile_one(src)
        extra = {}
        if t == "ai/vision":
            lock, pins = strip_torch(lock)
            header = ("# Installer AVANT requirements.txt, depuis l'index CPU de PyTorch :\n"
                      "#   pip install -r ai/vision/torch-cpu.txt --index-url https://download.pytorch.org/whl/cpu\n")
            extra[d / "torch-cpu.txt"] = header + "\n".join(pins) + "\n"
        for path, content in [(dst, lock), *extra.items()]:
            old = path.read_text(encoding="utf-8") if path.exists() else ""
            if old != content:
                stale.append(str(path.relative_to(ROOT)))
                if not a.check:
                    path.write_text(content, encoding="utf-8")
    if a.check and stale:
        sys.exit("Verrous obsolètes : " + ", ".join(stale) + "\nLancer : python tools/lock_deps.py")
    print(("À jour : " if a.check else "Générés : ") + (", ".join(stale) if stale else "rien à changer"))


if __name__ == "__main__":
    main()
