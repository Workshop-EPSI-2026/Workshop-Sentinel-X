#!/usr/bin/env python3
"""Vérifie la sécurité de Sentinel-X en marche, comme le ferait un attaquant du réseau, et produit une preuve.

    python tools/verifier_securite.py                      # sur le PC serveur, stack lancée par demarrer.ps1
    python tools/verifier_securite.py --hote 192.168.137.1 # depuis un autre PC du point d'accès (pentest croisé)
    python tools/verifier_securite.py --rapport docs/preuves/verification-securite.txt

Contrôles (aucune dépendance en dehors de Python) :
  configuration  secrets générés, mode MQTT, ca.key hors du serveur, aucun secret suivi par Git
  HTTPS          certificat signé par la CA locale, en-têtes de sécurité (HSTS, CSP, anti-iframe)
  API            refus sans jeton ou avec un faux jeton, santé sans détail, limitation de débit (429)
  vidéo          flux refusé sans ticket, vérification des tickets inaccessible de l'extérieur
  MQTT           connexion anonyme et faux mot de passe refusés, compte valide accepté ; 1883 fermé en mode TLS
  exposition     base de données, API interne, broker des services, Docker : injoignables depuis le réseau

Deux essais MQTT refusés seulement : en dessous du seuil de Sentinel Brain (5 refus en 60 s = attaque).
Code de sortie : 0 si aucun [KO].
"""
from __future__ import annotations

import argparse
import concurrent.futures
import http.client
import json
import re
import socket
import ssl
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / "infra" / ".env"
CERTS = ROOT / "security" / "certs"
SECRET_FILES = ("infra/.env", "infra/mosquitto/passwd", "firmware/sentinel_esp/secrets.h",
                "firmware/sentinel_esp/certs.h")

results: list[tuple[str, str, str]] = []


def report(status: str, what: str, detail: str = "") -> None:
    results.append((status, what, detail))
    print(f"[{status}] {what}" + (f" : {detail}" if detail else ""))


def ok(what: str, detail: str = "") -> None:
    report("OK", what, detail)


def ko(what: str, detail: str = "") -> None:
    report("KO", what, detail)


def warn(what: str, detail: str = "") -> None:
    report("!!", what, detail)


def read_env() -> dict[str, str]:
    if not ENV.exists():
        return {}
    out = {}
    for line in ENV.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\s*([A-Z_][A-Z0-9_]*)=(.*)$", line)
        if m:
            out[m.group(1)] = m.group(2).split(" #")[0].strip()
    return out


# ------------------------------------------------------------------ configuration (sur le PC serveur)
def check_config(env: dict[str, str]) -> None:
    print("\n== Configuration du serveur")
    if not env:
        warn("infra/.env introuvable", "contrôles de configuration ignorés (lancé hors du PC serveur ?)")
        return
    text = ENV.read_text(encoding="utf-8")
    (ko if "CHANGE_ME" in text else ok)("secrets générés", "CHANGE_ME restants" if "CHANGE_ME" in text else
                                        "aucun mot de passe par défaut")
    short = [k for k in ("API_KEY", "OPERATOR_TOKEN") if len(env.get(k, "")) < 32]
    (ko if short else ok)("clé d'API et jeton opérateur d'au moins 32 caractères", ", ".join(short))
    if env.get("MQTT_TLS") == "true":
        ok("MQTT chiffré (mode TLS)", f"services sur {env.get('MQTT_PORT')}, boîtiers sur 8883")
    else:
        warn("MQTT EN CLAIR (mode socle, 1883)", "mise au point seulement ; avant la démo : "
             "python tools/configurer.py --mode tls")
    if (CERTS / "ca.key").exists():
        warn("ca.key présente sur le serveur", "la ranger sur une clé USB : qui la vole peut fabriquer un faux boîtier")
    else:
        ok("ca.key absente du serveur")
    try:
        tracked = subprocess.run(["git", "ls-files", *SECRET_FILES, "security/certs"], cwd=ROOT, capture_output=True,
                                 text=True, check=False).stdout.split()
        tracked = [t for t in tracked if not t.endswith(".gitkeep")]
        (ko if tracked else ok)("aucun secret suivi par Git", ", ".join(tracked))
    except FileNotFoundError:
        warn("Git absent", "suivi des secrets non vérifié")


# ------------------------------------------------------------------ HTTPS, API, vidéo
class Https:
    def __init__(self, host: str, ca: Path | None):
        self.host = host
        if ca and ca.exists():
            self.ctx = ssl.create_default_context(cafile=str(ca))
            self.ctx.check_hostname = host in ("localhost", "127.0.0.1", "192.168.137.1", "sentinel-pc")
            self.verified = True
        else:
            self.ctx = ssl._create_unverified_context()   # noqa: S323 - ca.crt absent : on teste quand même le reste
            self.verified = False

    def request(self, method: str, path: str, headers: dict | None = None) -> tuple[int, dict, bytes]:
        c = http.client.HTTPSConnection(self.host, 443, context=self.ctx, timeout=5)
        try:
            c.request(method, path, headers=headers or {})
            r = c.getresponse()
            return r.status, {k.lower(): v for k, v in r.getheaders()}, r.read(4096)
        finally:
            c.close()


def check_web(host: str, env: dict[str, str]) -> None:
    print("\n== HTTPS et en-têtes")
    web = Https(host, CERTS / "ca.crt")
    try:
        status, headers, _ = web.request("GET", "/")
    except ssl.SSLCertVerificationError as e:
        ko("certificat HTTPS", f"non reconnu par la CA locale ({e.verify_message})")
        web = Https(host, None)
        status, headers, _ = web.request("GET", "/")
    except OSError as e:
        ko("dashboard joignable en HTTPS (443)", str(e))
        return
    if web.verified:
        ok("certificat HTTPS signé par la CA locale", host)
    else:
        warn("certificat HTTPS non vérifié", "security/certs/ca.crt absent sur ce poste")
    ok("dashboard servi en HTTPS", f"HTTP {status}")
    for name, label in (("strict-transport-security", "HSTS"), ("content-security-policy", "CSP"),
                        ("x-frame-options", "anti-iframe"), ("x-content-type-options", "nosniff")):
        (ok if name in headers else ko)(f"en-tête {label}", headers.get(name, "absent")[:70])
    (ko if "server" in headers and re.search(r"\d", headers["server"]) else ok)(
        "version de nginx masquée", headers.get("server", ""))

    print("\n== API")
    for label, hdrs in (("sans jeton", {}), ("faux jeton", {"Authorization": "Bearer faux-jeton-de-test"}),
                        ("clé des services à la place du jeton",
                         {"Authorization": f"Bearer {env['API_KEY']}"} if env.get("API_KEY") else None)):
        if hdrs is None:
            continue
        s, _, _ = web.request("GET", "/api/v1/alerts", hdrs)
        (ok if s == 401 else ko)(f"incidents refusés {label}", f"HTTP {s}")
    s, _, _ = web.request("POST", "/api/v1/alerts", {"Content-Type": "application/json"})
    (ok if s == 401 else ko)("ingestion d'alerte refusée sans clé de service", f"HTTP {s}")
    s, _, body = web.request("GET", "/api/v1/health")
    try:
        keys = set(json.loads(body))
    except ValueError:
        keys = set()
    (ok if s == 200 and keys <= {"status", "ts"} else ko)("santé publique sans détail", f"champs : {sorted(keys)}")
    if env.get("OPERATOR_TOKEN"):
        s, _, _ = web.request("GET", "/api/v1/alerts", {"Authorization": f"Bearer {env['OPERATOR_TOKEN']}"})
        (ok if s == 200 else ko)("le vrai jeton opérateur est accepté", f"HTTP {s}")

    def hit(_: int) -> int:
        try:
            return web.request("GET", "/api/v1/health")[0]
        except OSError:
            return 0
    with concurrent.futures.ThreadPoolExecutor(16) as pool:
        codes = list(pool.map(hit, range(120)))
    n429 = codes.count(429)
    (ok if n429 else ko)("limitation de débit de l'API (anti-DoS)", f"{n429} réponses 429 sur 120 requêtes rapides")
    time.sleep(3)                                          # laisse le seau se vider avant la suite

    print("\n== Flux vidéo")
    s, _, _ = web.request("GET", "/video")
    (ok if s == 401 else ko)("flux vidéo refusé sans ticket", f"HTTP {s}")
    if env.get("OPERATOR_TOKEN"):
        s, _, _ = web.request("GET", f"/video?token={env['OPERATOR_TOKEN']}")
        (ok if s == 401 else ko)("flux vidéo refusé avec le jeton opérateur dans l'URL", f"HTTP {s}")
    s, _, _ = web.request("GET", "/api/v1/video/check")
    (ok if s == 404 else ko)("vérification des tickets inaccessible de l'extérieur", f"HTTP {s}")


# ------------------------------------------------------------------ MQTT (paquet CONNECT minimal, sans bibliothèque)
def _utf8(s: str) -> bytes:
    b = s.encode()
    return len(b).to_bytes(2, "big") + b


def mqtt_connect(host: str, port: int, tls: bool, user: str | None, password: str | None) -> str:
    """Code de retour du broker : 'accepté', 'refusé (n)', ou l'erreur réseau / TLS."""
    flags = 0x02 | (0x80 if user else 0) | (0x40 if password else 0)
    payload = _utf8(f"verif-securite-{int(time.time())}") + (_utf8(user) if user else b"") + \
        (_utf8(password) if password else b"")
    body = _utf8("MQTT") + bytes([4, flags]) + (10).to_bytes(2, "big") + payload
    rem, n = b"", len(body)
    while True:
        byte, n = n % 128, n // 128
        rem += bytes([byte | (0x80 if n else 0)])
        if not n:
            break
    try:
        raw = socket.create_connection((host, port), timeout=5)
    except OSError as e:
        return f"injoignable ({e.__class__.__name__})"
    try:
        sock = raw
        if tls:
            ctx = ssl.create_default_context(cafile=str(CERTS / "ca.crt")) if (CERTS / "ca.crt").exists() \
                else ssl._create_unverified_context()     # noqa: S323
            ctx.check_hostname = False
            sock = ctx.wrap_socket(raw, server_hostname=host)
        sock.sendall(bytes([0x10]) + rem + body)
        ack = sock.recv(4)
        if len(ack) < 4 or ack[0] != 0x20:
            return "connexion fermée par le broker"
        return "accepté" if ack[3] == 0 else f"refusé (code {ack[3]})"
    except ssl.SSLError as e:
        return f"refusé en TLS ({e.reason})"
    except OSError as e:
        return f"fermé ({e.__class__.__name__})"
    finally:
        raw.close()


def check_mqtt(host: str, env: dict[str, str]) -> None:
    print("\n== MQTT")
    tls = env.get("MQTT_TLS") == "true" if env else True
    port = 8883 if tls else 1883
    r = mqtt_connect(host, port, tls, None, None)
    (ok if r.startswith(("refusé", "connexion fermée")) else ko)(f"connexion anonyme refusée ({port})", r)
    r = mqtt_connect(host, port, tls, "esp-01", "mauvais-mot-de-passe")
    (ok if r.startswith(("refusé", "connexion fermée")) else ko)(f"faux mot de passe refusé ({port})", r)
    if env.get("MQTT_MONITOR_PASSWORD"):
        r = mqtt_connect(host, port, tls, "monitor", env["MQTT_MONITOR_PASSWORD"])
        (ok if r == "accepté" else warn)(f"compte valide accepté ({port})", r + (
            " (TLS mutuel : certificat client exigé)" if r.startswith("refusé en TLS") else ""))
    if tls:
        r = mqtt_connect(host, 1883, False, None, None)
        (ok if r.startswith("injoignable") else ko)("MQTT en clair (1883) fermé", r)


# ------------------------------------------------------------------ exposition réseau
def check_exposure(host: str) -> None:
    print("\n== Ports qui ne doivent pas être joignables")
    ports = {5432: "PostgreSQL", 8000: "API sans nginx", 8884: "MQTT des services", 2375: "démon Docker"}
    if host not in ("localhost", "127.0.0.1"):
        ports[8001] = "vision (flux sans authentification)"
    for port, name in ports.items():
        try:
            socket.create_connection((host, port), timeout=2).close()
            ko(f"{name} ({port}) fermé", "JOIGNABLE")
        except OSError:
            ok(f"{name} ({port}) fermé")


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hote", default="localhost", help="adresse du PC serveur (défaut : localhost)")
    ap.add_argument("--rapport", help="écrit aussi le résultat dans ce fichier (preuve pour le dossier)")
    a = ap.parse_args(argv)
    env = read_env()
    print(f"Sentinel-X : vérification de sécurité de {a.hote} ({time.strftime('%d/%m/%Y %H:%M:%S')})")
    check_config(env)
    check_web(a.hote, env)
    check_mqtt(a.hote, env)
    check_exposure(a.hote)
    n_ko, n_warn = sum(r[0] == "KO" for r in results), sum(r[0] == "!!" for r in results)
    print(f"\nBilan : {len(results) - n_ko - n_warn} OK, {n_warn} à surveiller, {n_ko} KO")
    if a.rapport:
        lines = [f"Sentinel-X : vérification de sécurité de {a.hote}, {time.strftime('%d/%m/%Y %H:%M:%S')}", ""]
        lines += [f"[{s}] {w}" + (f" : {d}" if d else "") for s, w, d in results]
        lines += ["", f"Bilan : {len(results) - n_ko - n_warn} OK, {n_warn} à surveiller, {n_ko} KO"]
        # le jeton ne doit jamais finir dans une preuve partagée
        text = "\n".join(lines) + "\n"
        for k in ("OPERATOR_TOKEN", "API_KEY", "MQTT_MONITOR_PASSWORD"):
            if env.get(k):
                text = text.replace(env[k], "***")
        Path(a.rapport).parent.mkdir(parents=True, exist_ok=True)
        Path(a.rapport).write_text(text, encoding="utf-8")
        print(f"Rapport écrit : {a.rapport}")
    return 1 if n_ko else 0


if __name__ == "__main__":
    raise SystemExit(main())
