#!/usr/bin/env python3
"""
Sentinel-X — contrôle d'un poste de l'équipe, et de sa capacité à servir de serveur.

    python tools/doctor.py                     # poste : tout le projet est-il installé ?
    python tools/doctor.py --serveur           # + ce poste peut-il être LE serveur ? (matériel, Docker, webcam, YOLO)
    python3 tools/doctor.py --linux            # serveur Linux ou Raspberry Pi (portage)

N'importe quel poste de l'équipe peut être le serveur s'il passe --serveur sans [KO] (verifier-serveur.cmd).

[OK] conforme · [!!] à surveiller (n'empêche pas de travailler) · [KO] à corriger.
Code de sortie 1 s'il reste au moins un [KO] : utilisable dans un script.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import platform
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
RESULTS: list[tuple[str, str, str, str]] = []
CAPACITY: set[str] = set()      # contrôles qui décident si le poste PEUT être le serveur
SETUP: set[str] = set()         # réglages à faire une fois sur le poste choisi comme serveur


def run(cmd: list[str]) -> tuple[int, str]:
    exe = shutil.which(cmd[0])
    if exe is None:
        return 127, ""
    try:
        p = subprocess.run([exe, *cmd[1:]], capture_output=True, text=True, timeout=30)
        return p.returncode, (p.stdout + p.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)


def report(status: str, name: str, detail: str, fix: str = "") -> None:
    RESULTS.append((status, name, detail, fix))


def expected(file: str) -> str:
    return (ROOT / file).read_text(encoding="utf-8").strip()


# ----------------------------------------------------------------- contrôles communs
def check_git(pi: bool = False) -> None:
    rc, out = run(["git", "--version"])
    if rc:
        return report("KO", "Git", "absent", "winget install --id Git.Git -e")
    report("OK", "Git", out.replace("git version ", ""))
    _, crlf = run(["git", "config", "--get", "core.autocrlf"])
    if pi:
        pass
    elif crlf.strip() != "false":
        report("KO", "Git core.autocrlf", crlf or "non défini", "git config --global core.autocrlf false")
    else:
        report("OK", "Git core.autocrlf", "false")
    _, name = run(["git", "config", "--get", "user.name"])
    _, mail = run(["git", "config", "--get", "user.email"])
    if pi:
        pass
    elif not name or not mail:
        report("KO", "Git identité", "user.name ou user.email manquant",
               'git config --global user.name "Prénom Nom" ; git config --global user.email "..."')
    else:
        report("OK", "Git identité", f"{name} <{mail}>")
    _, remote = run(["git", "-C", str(ROOT), "remote", "get-url", "origin"])
    if "Workshop-EPSI-2026/Workshop-Sentinel-X" not in remote:
        report("!!", "Dépôt d'origine", remote or "inconnu",
               "git remote set-url origin https://github.com/Workshop-EPSI-2026/Workshop-Sentinel-X.git")
    else:
        report("OK", "Dépôt d'origine", "Workshop-EPSI-2026/Workshop-Sentinel-X")


def check_gh() -> None:
    rc, out = run(["gh", "--version"])
    if rc:
        return report("KO", "GitHub CLI", "absent", "winget install --id GitHub.cli -e")
    ver = out.splitlines()[0].replace("gh version ", "")
    rc, _ = run(["gh", "auth", "status"])
    report("OK" if rc == 0 else "!!", "GitHub CLI", ver + ("" if rc == 0 else " (non connecté)"),
           "" if rc == 0 else "gh auth login")


def check_python() -> None:
    want = expected(".python-version")
    have = f"{sys.version_info.major}.{sys.version_info.minor}"
    if have != want:
        report("KO", "Python", f"{platform.python_version()} (attendu {want}.x)",
               "winget install --id Python.Python.3.12 -e, puis recréer .venv avec py -3.12")
    else:
        report("OK", "Python", platform.python_version())
    in_venv = sys.prefix != sys.base_prefix
    venv_ok = in_venv and pathlib.Path(sys.prefix).resolve() == (ROOT / ".venv").resolve()
    if not venv_ok:
        report("KO", "Environnement .venv", "non activé" if not in_venv else f"autre venv : {sys.prefix}",
               r".venv\Scripts\activate  (Linux : source .venv/bin/activate)")
    else:
        report("OK", "Environnement .venv", "activé")


def check_locked(lockfile: str, label: str) -> None:
    try:
        from importlib.metadata import PackageNotFoundError, version

        from packaging.markers import Marker
        from packaging.utils import canonicalize_name
    except ImportError:
        return report("KO", label, "module packaging absent", f"pip install -r {lockfile}")
    bad, total = [], 0
    for line in (ROOT / lockfile).read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([A-Za-z0-9_.\-\[\]]+)==([^\s;]+)\s*(?:;\s*(.+))?$", line.strip())
        if not m:
            continue
        name, ver, marker = m.group(1).split("[")[0], m.group(2), m.group(3)
        if marker and not Marker(marker).evaluate():
            continue
        total += 1
        try:
            got = version(canonicalize_name(name))
        except PackageNotFoundError:
            bad.append(f"{name} absent")
            continue
        if got.split("+")[0] != ver.split("+")[0]:
            bad.append(f"{name} {got} au lieu de {ver}")
    if bad:
        report("KO", label, f"{len(bad)}/{total} écarts : " + ", ".join(bad[:4]) + (" …" if len(bad) > 4 else ""),
               f"pip install -r {lockfile}")
    else:
        report("OK", label, f"{total} paquets aux versions exactes")


def check_node() -> None:
    want = expected(".nvmrc")
    rc, out = run(["node", "--version"])
    if rc:
        return report("KO", "Node.js", "absent", f"winget install --id CoreyButler.NVMforWindows -e ; nvm install {want} ; nvm use {want}")
    major = out.lstrip("v").split(".")[0]
    ok = major.isdigit() and int(major) >= int(want)          # version de .nvmrc ou plus récente (Vite 8)
    report("OK" if ok else "KO", "Node.js", out + ("" if ok else f" (attendu {want}.x ou plus)"),
           "" if ok else f"nvm install {want} ; nvm use {want}")


def check_docker(required: bool, pi: bool = False) -> None:
    rc, out = run(["docker", "--version"])
    if rc:
        fix = ("curl -fsSL https://get.docker.com -o get-docker.sh && sudo sh get-docker.sh" if pi
               else "winget install --id Docker.DockerDesktop -e")
        return report("KO" if required else "!!", "Docker", "absent", fix)
    report("OK", "Docker", out.replace("Docker version ", ""))
    rc, out = run(["docker", "compose", "version"])
    m = re.search(r"v?(\d+)\.(\d+)", out or "")
    if rc or not m or int(m.group(1)) < 2:
        report("KO", "Docker Compose (v2 ou plus)", out or "absent", "mettre à jour Docker Desktop")
    else:
        report("OK", "Docker Compose (v2 ou plus)", out.split()[-1])
    rc, _ = run(["docker", "info"])
    if rc:
        report("!!", "Moteur Docker", "arrêté", "lancer Docker Desktop (Linux : sudo systemctl start docker)")


def check_mosquitto_clients() -> None:
    candidates = [shutil.which("mosquitto_sub"), r"C:\Program Files\mosquitto\mosquitto_sub.exe"]
    if any(c and os.path.exists(c) for c in candidates):
        report("OK", "Clients Mosquitto", "mosquitto_sub trouvé")
    else:
        report("!!", "Clients Mosquitto", "absents (utiles pour tester le broker)",
               "https://mosquitto.org/download/ puis ajouter C:\\Program Files\\mosquitto au Path")


def check_vscode() -> None:
    rc, out = run(["code", "--list-extensions"])
    if rc:
        return report("!!", "VS Code", "commande code introuvable", "winget install --id Microsoft.VisualStudioCode -e")
    have = {x.strip().lower() for x in out.splitlines()}
    wanted = json.loads((ROOT / ".vscode/extensions.json").read_text(encoding="utf-8"))["recommendations"]
    wanted = [w for w in wanted if w != "platformio.platformio-ide"]   # facultative : le firmware se fait dans l'Arduino IDE
    missing = [w for w in wanted if w.lower() not in have]
    report("OK" if not missing else "!!", "Extensions VS Code",
           "toutes présentes" if not missing else "manquantes : " + ", ".join(missing),
           "" if not missing else "code --install-extension <nom>")


def check_ssh_key() -> None:
    key = pathlib.Path.home() / ".ssh" / "id_ed25519.pub"
    report("OK" if key.exists() else "!!", "Clé SSH ed25519", str(key) if key.exists() else "absente",
           "" if key.exists() else 'ssh-keygen -t ed25519 -C "prenom@sentinel"')


def check_project_deps() -> None:
    """Dépendances de tout le projet : PyTorch CPU + vision (en plus de requirements-dev.txt), modèle YOLO."""
    torch_pin = [line for line in expected("ai/vision/torch-cpu.txt").splitlines() if line and not line.startswith("#")]
    fix = "pip install -r ai/vision/torch-cpu.txt --index-url https://download.pytorch.org/whl/cpu"
    try:
        from importlib.metadata import PackageNotFoundError, version
        got = version("torch").split("+")[0]
        want = torch_pin[0].split("==")[1]
        report("OK" if got == want else "KO", "PyTorch CPU", got + ("" if got == want else f" (attendu {want})"),
               "" if got == want else fix)
    except PackageNotFoundError:
        report("KO", "PyTorch CPU", "absent (requis par la vision)", fix)
    check_locked("ai/vision/requirements.txt", "Dépendances vision")
    model = ROOT / "ai/vision/models/yolov8n.pt"
    report("OK" if model.exists() else "KO", "Modèle YOLOv8n", "présent" if model.exists() else "absent",
           "" if model.exists() else "relancer installer.cmd (téléchargement de 6 Mo, une fois)")


# ----------------------------------------------------------------- fichiers de la stack
def check_stack_files() -> None:
    for rel, sev, fix in (
            ("infra/.env", "!!", "copy infra\\.env.example infra\\.env puis remplir les CHANGE_ME"),
            ("infra/mosquitto/passwd", "!!", "voir infra/mosquitto/README.md"),
            ("security/certs/ca.crt", "!!", "fourni par Lisa (tâche l1), requis dès le passage en TLS"),
            ):
        ok = (ROOT / rel).exists()
        report("OK" if ok else sev, rel, "présent" if ok else "absent", "" if ok else fix)
        SETUP.add(rel)
    env = ROOT / "infra" / ".env"
    if env.exists() and "CHANGE_ME" in env.read_text(encoding="utf-8"):
        report("!!", "infra/.env ", "contient encore des CHANGE_ME", "remplacer chaque CHANGE_ME par un secret")
        SETUP.add("infra/.env ")


# ----------------------------------------------------------------- ce poste peut-il être le serveur ?
MIN_RAM_GB, OK_RAM_GB = 7.5, 11.5          # Docker Desktop (~2 Go) + PostgreSQL + Brain + vision (~1,5 Go) + Windows
MIN_CORES, OK_CORES = 4, 6
MIN_DISK_GB, OK_DISK_GB = 15, 30       # images Docker (~3 Go), .venv avec PyTorch (~2 Go), base, journaux
MIN_FPS, OK_FPS = 5.0, 10.0            # YOLOv8n à 320 px sur le processeur


def capacity(status: str, name: str, detail: str, fix: str = "") -> None:
    report(status, name, detail, fix)
    CAPACITY.add(name)


def setup(status: str, name: str, detail: str, fix: str = "") -> None:
    report(status, name, detail, fix)
    SETUP.add(name)


def grade(value: float, minimum: float, good: float) -> str:
    return "OK" if value >= good else ("!!" if value >= minimum else "KO")


def powershell(cmd: str) -> tuple[int, str]:
    return run(["powershell", "-NoProfile", "-Command", cmd])


def total_ram_gb() -> float:
    try:
        import psutil
        return psutil.virtual_memory().total / 2**30
    except ImportError:
        pass
    if os.name == "nt":
        import ctypes

        class MemStatus(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        st = MemStatus()
        st.dwLength = ctypes.sizeof(MemStatus)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
        return st.ullTotalPhys / 2**30
    with open("/proc/meminfo", encoding="utf-8") as f:
        return int(f.readline().split()[1]) / 2**20


def check_hardware() -> None:
    if os.name == "nt":
        build = int(platform.version().split(".")[-1]) if platform.version().split(".")[-1].isdigit() else 0
        name = "Windows 11" if build >= 22000 else f"Windows 10 (build {build})"
        capacity("OK" if build >= 19041 else "KO", "Système", name,
                 "" if build >= 19041 else "Windows 10 2004 ou plus récent requis par Docker Desktop (WSL 2)")
    else:
        capacity("OK", "Système", f"{platform.system()} {platform.release()} (serveur : voir --linux)")
    ram = total_ram_gb()
    capacity(grade(ram, MIN_RAM_GB, OK_RAM_GB), "Mémoire vive", f"{ram:.1f} Go (minimum 8 Go, conseillé 12 Go)",
             "" if ram >= MIN_RAM_GB else "prendre le poste d'un collègue qui a plus de mémoire")
    cores = os.cpu_count() or 1
    capacity(grade(cores, MIN_CORES, OK_CORES), "Processeur", f"{cores} cœurs logiques (minimum {MIN_CORES})",
             "" if cores >= MIN_CORES else "prendre un poste plus puissant")
    free = shutil.disk_usage(ROOT).free / 2**30
    capacity(grade(free, MIN_DISK_GB, OK_DISK_GB), "Disque libre", f"{free:.0f} Go (minimum {MIN_DISK_GB})",
             "" if free >= MIN_DISK_GB else "libérer de la place (Téléchargements, corbeille)")
    if os.name == "nt":
        rc, out = run(["netsh", "wlan", "show", "interfaces"])
        wifi = rc == 0 and bool(re.search(r"^\s*(Name|Nom)\s*:", out, re.M))
        capacity("OK" if wifi else "KO", "Carte Wi-Fi (point d'accès)", "présente" if wifi else "absente",
                 "" if wifi else "il faut une carte Wi-Fi pour créer le réseau du boîtier (ou le routeur de secours)")
        rc, _ = run(["wsl", "--status"])
        capacity("OK" if rc == 0 else "KO", "WSL 2 (moteur de Docker Desktop)", "actif" if rc == 0 else "absent",
                 "" if rc == 0 else "PowerShell administrateur : wsl --install, puis redémarrer")


def check_webcam() -> None:
    os.environ.setdefault("OPENCV_LOG_LEVEL", "SILENT")      # pas de pavé d'avertissements si aucune caméra
    try:
        import cv2
    except ImportError:
        return capacity("KO", "Webcam 0", "OpenCV absent", "relancer installer.cmd")
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY)
    ok, frame = cap.read() if cap.isOpened() else (False, None)
    cap.release()
    capacity("OK" if ok else "KO", "Webcam 0", f"{frame.shape[1]}x{frame.shape[0]}" if ok else "aucune image",
             "" if ok else "brancher la webcam, fermer Teams/Zoom/Caméra qui l'occupent, ou VISION_SOURCE=1 dans infra/.env")


def check_yolo_speed() -> None:
    model = ROOT / "ai/vision/models/yolov8n.pt"
    if not model.exists():
        return capacity("KO", "Vitesse YOLO", "modèle absent, mesure impossible", "relancer installer.cmd")
    try:
        import time

        import numpy as np
        os.environ.setdefault("YOLO_OFFLINE", "1")
        from ultralytics import YOLO
    except ImportError:
        return capacity("KO", "Vitesse YOLO", "ultralytics absent", "relancer installer.cmd")
    yolo = YOLO(str(model))
    frame = (np.random.default_rng(0).random((480, 640, 3)) * 255).astype("uint8")
    for _ in range(3):
        yolo.predict(frame, imgsz=320, classes=[0], verbose=False)
    n, t0 = 15, time.perf_counter()
    for _ in range(n):
        yolo.predict(frame, imgsz=320, classes=[0], verbose=False)
    fps = n / (time.perf_counter() - t0)
    capacity(grade(fps, MIN_FPS, OK_FPS), "Vitesse YOLO (320 px)", f"{fps:.1f} images/s (minimum {MIN_FPS:.0f}, conseillé {OK_FPS:.0f})",
             "" if fps >= MIN_FPS else "poste trop lent pour la vision : secteur + mode performances, ou un autre poste")


def check_server_setup() -> None:
    """Réglages faits une fois sur le poste choisi (serveur-pc.ps1, .env, comptes MQTT) : n'empêchent pas le choix."""
    check_stack_files()
    if os.name != "nt":
        return
    rc, out = powershell("(Get-NetFirewallRule -DisplayName 'Sentinel-X*' | ForEach-Object DisplayName) -join ', '")
    setup("OK" if out.strip() else "!!", "Pare-feu (443, 8883)", out.strip() or "aucune règle Sentinel-X",
          "" if out.strip() else "PowerShell administrateur : tools\\serveur-pc.ps1")
    rc, out = powershell("(Get-NetIPAddress -IPAddress 192.168.137.1 -ErrorAction SilentlyContinue) -ne $null")
    hot = out.strip().lower() == "true"
    setup("OK" if hot else "!!", "Point d'accès (192.168.137.1)", "actif" if hot else "arrêté",
          "" if hot else "tools\\serveur-pc.ps1 -Action PointAcces (ou Paramètres > Point d'accès mobile, 2,4 GHz)")
    rc, out = powershell("(Get-ItemProperty 'HKLM:\\SYSTEM\\CurrentControlSet\\Services\\W32Time"
                         "\\TimeProviders\\NtpServer').Enabled")
    setup("OK" if out.strip() == "1" else "!!", "Serveur NTP pour l'ESP", "actif" if out.strip() == "1" else "inactif",
          "" if out.strip() == "1" else "tools\\serveur-pc.ps1 -Action Ntp")


# ----------------------------------------------------------------- serveur Linux / Raspberry Pi (portage)
def check_linux_server() -> None:
    rc, out = run(["vcgencmd", "get_throttled"])
    if rc == 0:
        report("OK" if out.strip().endswith("0x0") else "KO", "Bridage thermique (Raspberry Pi)", out,
               "" if out.strip().endswith("0x0") else "vérifier ventilateur et alimentation")
    rc, out = run(["systemctl", "is-active", "chrony"])
    first = out.splitlines()[0] if out else "inconnu"
    report("OK" if first == "active" else "!!", "chrony (NTP pour l'ESP)", first, "sudo apt install -y chrony")
    report("OK" if pathlib.Path("/dev/video0").exists() else "!!", "Webcam /dev/video0",
           "présente" if pathlib.Path("/dev/video0").exists() else "absente", "brancher la webcam USB")


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--serveur", action="store_true",
                    help="vérifie aussi que ce poste peut être le serveur (matériel, Docker, webcam, vitesse YOLO)")
    ap.add_argument("--linux", "--pi", dest="linux", action="store_true",
                    help="serveur Linux ou Raspberry Pi (stack et vision dans Docker)")
    ap.add_argument("--role", help=argparse.SUPPRESS)       # ancienne option : --role serveur = --serveur
    a = ap.parse_args()
    serveur = a.serveur or a.role == "serveur"

    check_git(pi=a.linux)
    if a.linux:
        check_docker(required=True, pi=True)
        check_stack_files()
        check_linux_server()
    else:
        check_gh()
        check_python()
        check_locked("requirements-dev.txt", "Dépendances Python")
        check_project_deps()
        check_node()
        check_docker(required=serveur)
        check_mosquitto_clients()
        check_vscode()
        check_ssh_key()
        if serveur:
            check_hardware()
            check_webcam()
            check_yolo_speed()
            check_server_setup()

    width = max(len(r[1]) for r in RESULTS)
    title = "serveur Linux" if a.linux else ("poste + capacité serveur" if serveur else "poste")
    print(f"\nSentinel-X · contrôle {title}\n")
    for status, name, detail, fix in RESULTS:
        print(f"  [{status}] {name.ljust(width)}  {detail}")
        if fix and status != "OK":
            print(f"        {''.ljust(width)}  -> {fix}")
    ko = sum(1 for r in RESULTS if r[0] == "KO")
    warn = sum(1 for r in RESULTS if r[0] == "!!")
    print(f"\n  {len(RESULTS) - ko - warn} OK · {warn} à surveiller · {ko} à corriger")
    if serveur and not a.linux:
        blocking = [r[1] for r in RESULTS if r[0] == "KO" and (r[1] in CAPACITY or r[1].startswith("Docker"))]
        todo = [r[1] for r in RESULTS if r[0] != "OK" and r[1] in SETUP]
        if blocking:
            print("\n  VERDICT : ce poste NE PEUT PAS être le serveur (" + ", ".join(blocking) + ").")
        else:
            print("\n  VERDICT : ce poste PEUT être le serveur.")
            if todo:
                print("  Réglages à faire une fois s'il est choisi : " + ", ".join(t.strip() for t in todo)
                      + " (tools\\serveur-pc.ps1 en administrateur, puis infra\\.env et comptes MQTT).")
    sys.exit(1 if ko else 0)


if __name__ == "__main__":
    main()
