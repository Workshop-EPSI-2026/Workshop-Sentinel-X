#!/usr/bin/env python3
"""Prépare la configuration locale du serveur en une commande : infra/.env et les comptes MQTT (infra/mosquitto/passwd).

    python tools/configurer.py            # crée ce qui manque, ne touche pas à ce qui existe déjà
    python tools/configurer.py --afficher # réaffiche les mots de passe des comptes esp-01 et monitor
    python tools/configurer.py --refaire  # régénère tous les secrets (les anciens ne marchent plus)

- infra/.env : copie de infra/.env.example, chaque CHANGE_ME remplacé par un secret aléatoire, mode socle (1883),
  profils « app,ai » (API, dashboard, Sentinel Brain).
- security/certs : CA locale et certificats (security/pki/pki.py), s'ils n'existent pas encore (HTTPS du dashboard).
- infra/mosquitto/passwd : comptes esp-01, vision, api, anomaly, notify, monitor, hachés au format de Mosquitto 2
  (PBKDF2-SHA512), avec les mêmes mots de passe que infra/.env. Pas besoin de Docker pour cette étape.

Ces deux fichiers sont ignorés par Git : ils ne quittent jamais le poste.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import os
import re
import secrets
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV, EXAMPLE = ROOT / "infra" / ".env", ROOT / "infra" / ".env.example"
PASSWD = ROOT / "infra" / "mosquitto" / "passwd"
# compte MQTT -> variable de .env qui porte son mot de passe
ACCOUNTS = {"esp-01": "MQTT_ESP_PASSWORD", "vision": "MQTT_VISION_PASSWORD", "api": "MQTT_API_PASSWORD",
            "anomaly": "MQTT_ANOMALY_PASSWORD", "notify": "MQTT_NOTIFY_PASSWORD",
            "monitor": "MQTT_MONITOR_PASSWORD"}
EXTRA = """
# --- Comptes du boîtier et des tests (ajoutés par tools/configurer.py) ----------
MQTT_ESP_PASSWORD={esp}         # à recopier dans firmware/sentinel_esp/secrets.h (MQTT_PASSWORD)
MQTT_MONITOR_PASSWORD={mon}     # lecture seule de sentinel/# : mosquitto_sub, tests
"""


def mosquitto_hash(password: str, iterations: int = 101) -> str:
    """Format $7$ de mosquitto_passwd (Mosquitto 2.x) : PBKDF2-HMAC-SHA512, sel de 12 octets."""
    salt = os.urandom(12)
    dk = hashlib.pbkdf2_hmac("sha512", password.encode("utf-8"), salt, iterations, dklen=64)
    return f"$7${iterations}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def read_env(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\s*([A-Z_][A-Z0-9_]*)=(.*)$", line)
        if m:
            values[m.group(1)] = m.group(2).split(" #")[0].strip()
    return values


def create_env() -> None:
    text = EXAMPLE.read_text(encoding="utf-8")
    text = re.sub(r"CHANGE_ME\w*", lambda m: secrets.token_urlsafe(32 if "32" in m.group(0) else 24), text)
    text = re.sub(r"(?m)^COMPOSE_PROFILES=.*$", "COMPOSE_PROFILES=app,ai", text)
    text += EXTRA.format(esp=secrets.token_urlsafe(24), mon=secrets.token_urlsafe(24))
    ENV.write_text(text, encoding="utf-8", newline="\n")


def complete_env(values: dict[str, str]) -> dict[str, str]:
    """Complète un .env créé par une version précédente : comptes et réglages ajoutés depuis, sans rien changer
    à ce qui existe (les mots de passe déjà donnés à l'ESP restent valables)."""
    add = []
    if not values.get("MQTT_ESP_PASSWORD") and not values.get("MQTT_MONITOR_PASSWORD"):
        add.append(EXTRA.format(esp=secrets.token_urlsafe(24), mon=secrets.token_urlsafe(24)))
    for var in ACCOUNTS.values():
        if var not in values and var not in "".join(add):
            add.append(f"{var}={secrets.token_urlsafe(24)}\n")
    if "SMTP_HOST" not in values:
        example = EXAMPLE.read_text(encoding="utf-8")
        start = example.index("# --- Notifications")
        add.append("\n" + example[start:example.index("# --- Vision")])
    if add:
        with ENV.open("a", encoding="utf-8", newline="\n") as f:
            f.write("".join(add))
    return read_env(ENV)


def write_passwd(values: dict[str, str]) -> None:
    lines = [f"{user}:{mosquitto_hash(values[var])}" for user, var in ACCOUNTS.items()]
    PASSWD.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refaire", action="store_true", help="régénère .env et passwd (nouveaux secrets)")
    ap.add_argument("--afficher", action="store_true", help="affiche seulement les mots de passe esp-01 et monitor")
    a = ap.parse_args(argv)

    if a.afficher:
        if not ENV.exists():
            print("infra/.env absent : lancer d'abord python tools/configurer.py")
            return 1
        v = read_env(ENV)
        print(f"esp-01  : {v.get('MQTT_ESP_PASSWORD', '?')}\nmonitor : {v.get('MQTT_MONITOR_PASSWORD', '?')}\n"
              f"jeton opérateur (connexion au dashboard) : {v.get('OPERATOR_TOKEN', '?')}")
        return 0

    if a.refaire or not ENV.exists():
        create_env()
        print("[OK] infra/.env créé (secrets aléatoires, MQTT 1883 en clair authentifié, profils app et ai)")
    elif "CHANGE_ME" in ENV.read_text(encoding="utf-8"):
        print("[KO] infra/.env existe mais contient encore des CHANGE_ME : le corriger, ou relancer avec --refaire")
        return 1
    else:
        print("[OK] infra/.env existant conservé")
    values = complete_env(read_env(ENV))
    if values.get("COMPOSE_PROFILES") == "ai":           # .env d'avant le dashboard : on ajoute l'API et le dashboard
        text = re.sub(r"(?m)^COMPOSE_PROFILES=ai\s*$", "COMPOSE_PROFILES=app,ai", ENV.read_text(encoding="utf-8"))
        ENV.write_text(text, encoding="utf-8", newline="\n")
        values = read_env(ENV)
        print("[OK] infra/.env : profils app et ai (API et dashboard ajoutés)")

    missing = [var for var in ACCOUNTS.values() if not values.get(var)]
    if missing:
        print(f"[KO] infra/.env : variables vides {', '.join(missing)} (relancer avec --refaire)")
        return 1
    # passwd découle toujours de .env : le réécrire garde les mêmes mots de passe et ajoute les nouveaux comptes
    write_passwd(values)
    print("[OK] infra/mosquitto/passwd à jour : comptes " + ", ".join(ACCOUNTS))
    pki = ROOT / "security" / "pki" / "pki.py"
    if a.refaire or not (ROOT / "security" / "certs" / "server.crt").exists():
        print("[..] certificats (security/pki/pki.py) :")
        subprocess.run([sys.executable, str(pki)] + (["--refaire"] if a.refaire else []), check=False)

    print("\nMots de passe à connaître (aussi dans infra/.env, jamais commité) :")
    print(f"  esp-01  : {values['MQTT_ESP_PASSWORD']}   -> firmware/sentinel_esp/secrets.h, MQTT_PASSWORD")
    print(f"  monitor : {values['MQTT_MONITOR_PASSWORD']}   -> pour regarder les messages (mosquitto_sub)")
    print(f"  jeton opérateur : {values.get('OPERATOR_TOKEN', '?')}   -> connexion au dashboard")
    if not values.get("SMTP_HOST"):
        print("\nMails d'alerte : pas encore configurés (SMTP_* et NOTIFY_TO dans infra/.env) ; la voix fonctionne déjà.")
    print("\nÉtape suivante : powershell -ExecutionPolicy Bypass -File tools\\demarrer.ps1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
