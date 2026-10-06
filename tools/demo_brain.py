#!/usr/bin/env python3
"""Démonstration de Sentinel Brain sans broker ni Docker : le simulateur du boîtier joue des scénarios
(fuite de gaz, incendie, intrusion, effraction, rejeu, brouillage, dérive), Brain les analyse en direct et
affiche ses scores et ses incidents dans la console.

    python tools/demo_brain.py                  # tous les scénarios, ~2 min simulées par seconde
    python tools/demo_brain.py --vitesse 600    # plus rapide
    python tools/demo_brain.py --scenario gas_leak

Lancé par demo.cmd (avec la vision). Rien n'est envoyé sur le réseau.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "ai" / "anomaly"))

from brain.config import BrainConfig  # noqa: E402
from brain.engine import SentinelBrain  # noqa: E402

SCENARIOS = ["drift", "gas_leak", "fire", "intrusion", "tamper", "replay", "jamming"]
NOMS = {"normal": "régime normal", "drift": "dérive thermique (panne de climatisation)",
        "gas_leak": "fuite de gaz", "fire": "début d'incendie", "intrusion": "intrusion dans la salle",
        "tamper": "ouverture du boîtier (effraction)", "replay": "attaque par rejeu de messages",
        "jamming": "brouillage Wi-Fi", "learning": "apprentissage"}
GRAVITE = {"info": "INFO", "warning": "ALERTE", "critical": "CRITIQUE"}


def horloge(t: float, t0: float) -> str:
    s = int(t - t0)
    return f"T+{s // 3600:d}h{(s % 3600) // 60:02d}m{s % 60:02d}s"


def barre(score: float) -> str:
    n = int(round(score / 5))
    return "#" * n + "." * (20 - n)


def generer(scenario: str, tmp: Path, seed: int) -> Path:
    log = tmp / "rx.jsonl"
    cmd = [sys.executable, str(ROOT / "tools" / "simulator.py"), "--no-mqtt", "--speed", "100000", "--seed", str(seed),
           "--scenario", scenario, "--warmup", "900", "--cooldown", "600", "--rx-log", str(log)]
    subprocess.run(cmd, check=True, capture_output=True)
    return log


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenario", choices=SCENARIOS + ["all"], default="all")
    ap.add_argument("--vitesse", type=float, default=120.0, help="secondes simulées par seconde réelle (0 = sans pause)")
    ap.add_argument("--graine", type=int, default=42, help="graine du simulateur (autres données simulées)")
    ap.add_argument("--score-toutes", type=float, default=60.0, help="affiche le score toutes les N secondes simulées")
    a = ap.parse_args(argv)

    print("Sentinel Brain : démonstration hors ligne (simulateur du boîtier esp-01, aucune donnée réseau)")
    print("Préparation des données simulées...", flush=True)
    with tempfile.TemporaryDirectory() as tmp:
        lines = generer(a.scenario, Path(tmp), a.graine).read_text(encoding="utf-8").splitlines()
    msgs = [json.loads(x) for x in lines]
    if not msgs:
        print("Aucune donnée générée.")
        return 1
    t0 = msgs[0]["rx_ts"]
    print(f"{len(msgs)} messages, {(msgs[-1]['rx_ts'] - t0) / 60:.0f} minutes simulées.")
    print("Les 10 premières minutes sont l'apprentissage du lieu : Brain n'alerte pas pendant ce temps.\n")

    brain = SentinelBrain(BrainConfig())
    label, last_score_t, alerts = None, -1e9, 0
    reel0, sim0 = time.monotonic(), t0
    for m in msgs:
        t = m["rx_ts"]
        if a.vitesse > 0:
            attente = (t - sim0) / a.vitesse - (time.monotonic() - reel0)
            if attente > 0:
                time.sleep(min(attente, 2.0))
        if m.get("label") != label:
            label = m.get("label") or "normal"
            nom = ("retour au calme après " + NOMS.get(label[:-9], label[:-9])) if label.endswith("_recovery") \
                else NOMS.get(label, label)
            print(f"\n{horloge(t, t0)}  ---- scénario : {nom} ----", flush=True)
        for out in brain.handle(m["topic"], m["payload"], t):
            p = out["payload"]
            if out["kind"] == "score" and p.get("device_id") == "esp-01" and t - last_score_t >= a.score_toutes:
                last_score_t = t
                etat = " (apprentissage)" if p.get("learning") else ""
                eta = f"  critique dans {p['eta_min']:.1f} min" if p.get("eta_min") is not None else ""
                print(f"{horloge(t, t0)}  score {p['score']:3.0f} [{barre(p['score'])}]  environnement "
                      f"{p['environment']:3.0f} · physique {p['physical']:3.0f} · cyber {p['cyber']:3.0f}{etat}{eta}",
                      flush=True)
            elif out["kind"] == "alert":
                alerts += 1
                facteurs = ", ".join(f"{f['name']}={f['value']}" for f in p.get("factors", [])[:3])
                eta = f" · critique dans {p['eta_min']:.1f} min" if p.get("eta_min") is not None else ""
                print(f"{horloge(t, t0)}  >>> {GRAVITE.get(p['severity'], p['severity'])} {p['type']} "
                      f"(score {p['score']}{eta})\n               {p['explanation']}"
                      + (f"\n               facteurs : {facteurs}" if facteurs else ""), flush=True)
    print(f"\nFin de la démonstration : {alerts} alertes émises par Brain.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
