#!/usr/bin/env python3
"""
Sentinel-X — contrôle de l'environnement d'un poste, du PC serveur ou d'un serveur Linux / Raspberry Pi.

    python tools/doctor.py                     # poste, rôle commun
    python tools/doctor.py --role ia           # + contrôles du rôle (ia, iot, cyber, integration, fablab)
    python tools/doctor.py --role serveur      # PC serveur Windows : Docker, vision, webcam, pare-feu, point d'accès
    python3 tools/doctor.py --linux            # serveur Linux ou Raspberry Pi (portage)

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
    report("OK" if major == want else "KO", "Node.js", out + ("" if major == want else f" (attendu {want}.x)"),
           "" if major == want else f"nvm install {want} ; nvm use {want}")


def check_docker(required: bool, pi: bool = False) -> None:
    rc, out = run(["docker", "--version"])
    if rc:
        fix = ("curl -fsSL https://get.docker.com -o get-docker.sh && sudo sh get-docker.sh" if pi
               else "winget install --id Docker.DockerDesktop -e")
        return report("KO" if required else "!!", "Docker", "absent", fix)
    report("OK", "Docker", out.replace("Docker version ", ""))
    rc, out = run(["docker", "compose", "version"])
    if rc or "v2" not in out and " 2." not in out:
        report("KO", "Docker Compose v2", out or "absent", "mettre à jour Docker")
    else:
        report("OK", "Docker Compose v2", out.split()[-1])
    rc, _ = run(["docker", "info"])
    if rc:
        report("!!", "Moteur Docker", "arrêté", "lancer Docker Desktop (Linux : sudo systemctl start docker)")


def check_mosquitto_clients() -> None:
    candidates = [shutil.which("mosquitto_sub"), r"C:\Program Files\mosquitto\mosquitto_sub.exe"]
    if any(c and os.path.exists(c) for c in candidates):
        report("OK", "Clients Mosquitto", "mosquitto_sub trouvé")
    else:
        report("KO", "Clients Mosquitto", "absents",
               "https://mosquitto.org/download/ puis ajouter C:\\Program Files\\mosquitto au Path")


def check_vscode(role: str) -> None:
    rc, out = run(["code", "--list-extensions"])
    if rc:
        return report("!!", "VS Code", "commande code introuvable", "winget install --id Microsoft.VisualStudioCode -e")
    have = {x.strip().lower() for x in out.splitlines()}
    wanted = json.loads((ROOT / ".vscode/extensions.json").read_text(encoding="utf-8"))["recommendations"]
    if role != "iot":
        wanted = [w for w in wanted if w != "platformio.platformio-ide"]
    missing = [w for w in wanted if w.lower() not in have]
    report("OK" if not missing else "!!", "Extensions VS Code",
           "toutes présentes" if not missing else "manquantes : " + ", ".join(missing),
           "" if not missing else "code --install-extension <nom>")


def check_ssh_key() -> None:
    key = pathlib.Path.home() / ".ssh" / "id_ed25519.pub"
    report("OK" if key.exists() else "!!", "Clé SSH ed25519", str(key) if key.exists() else "absente",
           "" if key.exists() else 'ssh-keygen -t ed25519 -C "prenom@sentinel"')


def check_role(role: str) -> None:
    if role in ("ia", "serveur"):
        torch_pin = [line for line in expected("ai/vision/torch-cpu.txt").splitlines() if line and not line.startswith("#")]
        try:
            from importlib.metadata import version

            import torch  # noqa: F401
            got = version("torch").split("+")[0]
            want = torch_pin[0].split("==")[1]
            report("OK" if got == want else "KO", "PyTorch CPU", got,
                   "" if got == want else "pip install -r ai/vision/torch-cpu.txt --index-url https://download.pytorch.org/whl/cpu")
        except ImportError:
            report("KO" if role == "serveur" else "!!", "PyTorch CPU", "absent (requis par la vision)",
                   "pip install -r ai/vision/torch-cpu.txt --index-url https://download.pytorch.org/whl/cpu")
        check_locked("ai/vision/requirements.txt", "Dépendances vision")
    if role == "cyber":
        for tool, fix in (("nmap", "winget install --id Insecure.Nmap -e"),
                          ("openssl", "fourni par Git Bash (C:\\Program Files\\Git\\usr\\bin)")):
            report("OK" if shutil.which(tool) else "!!", tool, "trouvé" if shutil.which(tool) else "absent du Path", fix)
    if role == "iot":
        pio = shutil.which("pio") or (pathlib.Path.home() / ".platformio" / "penv").exists()
        report("OK" if pio else "!!", "PlatformIO", "installé" if pio else "pas encore initialisé",
               "ouvrir le dossier firmware/ dans VS Code avec l'extension PlatformIO")


# ----------------------------------------------------------------- fichiers de la stack
def check_stack_files() -> None:
    for rel, sev, fix in (
            ("infra/.env", "KO", "copy infra\\.env.example infra\\.env puis remplir les CHANGE_ME"),
            ("infra/mosquitto/passwd", "KO", "voir infra/mosquitto/README.md"),
            ("security/certs/ca.crt", "!!", "fourni par Lisa (tâche l1), requis dès le passage en TLS"),
            ("ai/vision/models/yolov8n.pt", "!!", "tools\\setup-poste.ps1 -Role serveur (téléchargement, une fois)")):
        ok = (ROOT / rel).exists()
        report("OK" if ok else sev, rel, "présent" if ok else "absent", "" if ok else fix)
    env = ROOT / "infra" / ".env"
    if env.exists() and "CHANGE_ME" in env.read_text(encoding="utf-8"):
        report("KO", "infra/.env", "contient encore des CHANGE_ME", "remplacer chaque CHANGE_ME par un secret")


# ----------------------------------------------------------------- PC serveur Windows
def powershell(cmd: str) -> tuple[int, str]:
    return run(["powershell", "-NoProfile", "-Command", cmd])


def check_windows_server() -> None:
    rc, out = run(["wsl", "--status"])
    report("OK" if rc == 0 else "KO", "WSL 2 (moteur de Docker Desktop)", "actif" if rc == 0 else "absent",
           "" if rc == 0 else "wsl --install, puis redémarrer")
    rc, out = powershell("(Get-NetFirewallRule -DisplayName 'Sentinel-X*' | ForEach-Object DisplayName) -join ', '")
    report("OK" if out.strip() else "KO", "Pare-feu (443, 8883)", out.strip() or "aucune règle Sentinel-X",
           "" if out.strip() else "PowerShell administrateur : tools\\serveur-pc.ps1 -Action PareFeu")
    rc, out = powershell("(Get-NetIPAddress -IPAddress 192.168.137.1 -ErrorAction SilentlyContinue) -ne $null")
    hot = out.strip().lower() == "true"
    report("OK" if hot else "!!", "Point d'accès (192.168.137.1)", "actif" if hot else "arrêté",
           "" if hot else "tools\\serveur-pc.ps1 -Action PointAcces (ou Paramètres > Point d'accès mobile, 2,4 GHz)")
    rc, out = powershell("(Get-ItemProperty 'HKLM:\\SYSTEM\\CurrentControlSet\\Services\\W32Time"
                         "\\TimeProviders\\NtpServer').Enabled")
    report("OK" if out.strip() == "1" else "!!", "Serveur NTP pour l'ESP", "actif" if out.strip() == "1" else "inactif",
           "" if out.strip() == "1" else "tools\\serveur-pc.ps1 -Action Ntp")
    check_webcam()


def check_webcam() -> None:
    try:
        import cv2
    except ImportError:
        return report("KO", "Webcam", "OpenCV absent", "tools\\setup-poste.ps1 -Role serveur")
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY)
    ok, frame = cap.read() if cap.isOpened() else (False, None)
    cap.release()
    report("OK" if ok else "KO", "Webcam 0", f"{frame.shape[1]}x{frame.shape[0]}" if ok else "aucune image",
           "" if ok else "brancher la webcam, fermer Teams/Zoom/Caméra qui l'occupent, ou VISION_SOURCE=1 dans infra/.env")


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
    ap.add_argument("--role", choices=["commun", "ia", "iot", "cyber", "integration", "fablab", "serveur"],
                    default="commun")
    ap.add_argument("--linux", "--pi", dest="linux", action="store_true",
                    help="serveur Linux ou Raspberry Pi (stack et vision dans Docker)")
    a = ap.parse_args()

    check_git(pi=a.linux)
    if a.linux:
        check_docker(required=True, pi=True)
        check_stack_files()
        check_linux_server()
    else:
        check_gh()
        check_python()
        check_locked("requirements-dev.txt", "Dépendances Python")
        check_node()
        check_docker(required=a.role in ("integration", "ia", "serveur"))
        check_mosquitto_clients()
        check_vscode(a.role)
        check_ssh_key()
        check_role(a.role)
        if a.role == "serveur":
            check_stack_files()
            if os.name == "nt":
                check_windows_server()
            else:
                check_webcam()

    width = max(len(r[1]) for r in RESULTS)
    print(f"\nSentinel-X · contrôle {'serveur Linux' if a.linux else 'poste'} · rôle {a.role}\n")
    for status, name, detail, fix in RESULTS:
        print(f"  [{status}] {name.ljust(width)}  {detail}")
        if fix and status != "OK":
            print(f"        {''.ljust(width)}  -> {fix}")
    ko = sum(1 for r in RESULTS if r[0] == "KO")
    warn = sum(1 for r in RESULTS if r[0] == "!!")
    print(f"\n  {len(RESULTS) - ko - warn} OK · {warn} à surveiller · {ko} à corriger")
    sys.exit(1 if ko else 0)


if __name__ == "__main__":
    main()
