#!/usr/bin/env python3
"""PKI locale de Sentinel-X (ECDSA P-256), selon security/README.md. Aucune clé n'est versionnée.

    python security/pki/pki.py              # crée ce qui manque dans security/certs (ne remplace rien)
    python security/pki/pki.py --refaire    # nouvelle CA et nouveaux certificats (les anciens ne marchent plus)

Produit dans security/certs/ :
  ca.crt / ca.key            autorité locale (ca.key ensuite sur une clé USB, pas sur le PC serveur)
  server.crt / server.key    Mosquitto (8883, 8884) et nginx (443) ; SAN : 192.168.137.1, 127.0.0.1, localhost,
                             sentinel-pc, mosquitto, host.docker.internal
  <client>.crt / .key        certificats clients (TLS mutuel), CN = compte MQTT : esp-01, vision, notify, monitor
et firmware/sentinel_esp/certs.h (CA, certificat et clé d'esp-01) pour le sketch Arduino.

Utilise openssl : celui du système, ou celui fourni avec Git pour Windows.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CERTS = ROOT / "security" / "certs"
SAN = "IP:192.168.137.1,IP:127.0.0.1,DNS:localhost,DNS:sentinel-pc,DNS:mosquitto,DNS:host.docker.internal"
CLIENTS = ("esp-01", "vision", "notify", "monitor")
DAYS_CA, DAYS = 1825, 825


def find_openssl() -> str:
    for cand in (shutil.which("openssl"), r"C:\Program Files\Git\usr\bin\openssl.exe",
                 r"C:\Program Files\Git\mingw64\bin\openssl.exe"):
        if cand and Path(cand).exists():
            return cand
    sys.exit("openssl introuvable : installer Git pour Windows (il le fournit), puis relancer.")


def run(openssl: str, *args: str) -> None:
    env = dict(os.environ, MSYS_NO_PATHCONV="1")       # Git Bash : ne pas convertir « /CN=... » en chemin
    p = subprocess.run([openssl, *args], capture_output=True, text=True, env=env)
    if p.returncode:
        sys.exit(f"openssl {' '.join(args[:2])} a échoué :\n{p.stderr.strip()}")


def key(openssl: str, path: Path) -> None:
    run(openssl, "ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", str(path))


def sign(openssl: str, name: str, subject: str, ext: str) -> None:
    k, csr, crt = CERTS / f"{name}.key", CERTS / f"{name}.csr", CERTS / f"{name}.crt"
    key(openssl, k)
    run(openssl, "req", "-new", "-key", str(k), "-subj", subject, "-out", str(csr))
    with tempfile.NamedTemporaryFile("w", suffix=".ext", delete=False, encoding="ascii") as f:
        f.write(ext)
    try:
        run(openssl, "x509", "-req", "-in", str(csr), "-CA", str(CERTS / "ca.crt"), "-CAkey", str(CERTS / "ca.key"),
            "-CAcreateserial", "-days", str(DAYS), "-sha256", "-extfile", f.name, "-out", str(crt))
    finally:
        os.unlink(f.name)
        csr.unlink(missing_ok=True)


def certs_h(esp: str = "esp-01") -> str:
    def raw(name: str) -> str:
        return (CERTS / name).read_text(encoding="ascii").strip()
    return ("// Genere par security/pki/pki.py - NE PAS COMMITER (ignore par Git)\n#pragma once\n\n"
            f'static const char CA_CERT[] PROGMEM = R"EOF(\n{raw("ca.crt")}\n)EOF";\n\n'
            f'static const char CLIENT_CERT[] PROGMEM = R"EOF(\n{raw(esp + ".crt")}\n)EOF";\n\n'
            f'static const char CLIENT_KEY[] PROGMEM = R"EOF(\n{raw(esp + ".key")}\n)EOF";\n')


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refaire", action="store_true", help="recrée la CA et tous les certificats")
    a = ap.parse_args(argv)
    openssl = find_openssl()
    CERTS.mkdir(parents=True, exist_ok=True)
    if a.refaire:
        for f in CERTS.glob("*"):
            if f.suffix in (".crt", ".key", ".srl"):
                f.unlink()

    made = []
    if not (CERTS / "ca.crt").exists():
        key(openssl, CERTS / "ca.key")
        run(openssl, "req", "-x509", "-new", "-key", str(CERTS / "ca.key"), "-sha256", "-days", str(DAYS_CA),
            "-subj", "/O=Sentinel-X/CN=Sentinel-X CA locale",
            "-addext", "basicConstraints=critical,CA:TRUE", "-addext", "keyUsage=critical,keyCertSign,cRLSign",
            "-out", str(CERTS / "ca.crt"))
        made.append("ca")
    elif not (CERTS / "ca.key").exists():
        missing = [n for n in ("server", *CLIENTS) if not (CERTS / f"{n}.crt").exists()]
        if missing:
            sys.exit("ca.key absente (rangée sur la clé USB ?) : la remettre dans security/certs pour signer "
                     + ", ".join(missing) + ", puis la retirer.")
    if not (CERTS / "server.crt").exists():
        sign(openssl, "server", "/O=Sentinel-X/CN=sentinel-pc",
             "basicConstraints=CA:FALSE\nkeyUsage=critical,digitalSignature,keyAgreement\n"
             f"extendedKeyUsage=serverAuth\nsubjectAltName={SAN}\n")
        made.append("server")
    for cn in CLIENTS:
        if not (CERTS / f"{cn}.crt").exists():
            sign(openssl, cn, f"/O=Sentinel-X/CN={cn}",
                 "basicConstraints=CA:FALSE\nkeyUsage=critical,digitalSignature\nextendedKeyUsage=clientAuth\n")
            made.append(cn)
    (CERTS / "ca.srl").unlink(missing_ok=True)

    target = ROOT / "firmware" / "sentinel_esp" / "certs.h"
    if (CERTS / "esp-01.key").exists() and (made or not target.exists()):
        target.write_text(certs_h(), encoding="ascii", newline="\n")
        made.append("firmware/sentinel_esp/certs.h")

    print(("[OK] créés : " + ", ".join(made)) if made else "[OK] PKI déjà en place (--refaire pour tout recréer)")
    print("     security/certs/ et certs.h ne sont jamais commités. Ranger ca.key sur une clé USB après usage.")
    print("     Navigateur sans avertissement : importer security\\certs\\ca.crt dans « Autorités de certification "
          "racines de confiance » (certmgr.msc).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
