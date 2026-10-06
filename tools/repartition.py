#!/usr/bin/env python3
"""Régénère docs/repartition.md depuis .github/kanban/tasks.yml et team.yml (ne jamais l'éditer à la main).

    python tools/repartition.py
"""
from __future__ import annotations

import pathlib

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
FOLDERS = {
    "Constantin": "`api/`, `dashboard/`, `infra/` (co), `config/` (co), `.github/`, `docs/`",
    "Jeffrick": "`ai/` (vision, Sentinel Brain), `config/` (co), `tools/`, schéma BDD (`infra/postgres/`)",
    "Momo": "`firmware/`, `docs/cablage.md`",
    "Lisa": "`security/`, `infra/mosquitto/` (co), `docs/securite.md`, `docs/preuves/`",
    "Michel": "`infra/` (co, PC serveur), `docs/reseau.md`, `docs/fablab/`",
}
DECISIONS = """- **Matériel réel** : ESP32-S3 N16R8, DHT11, module MQ-2, PIR HW-416-B, webcam USB, PC portable Windows 11.
- **Option B** : le PC portable est le serveur (point d'accès Wi-Fi, Docker Desktop, vision sur la webcam).
  Un deuxième PC sert de secours ; la solution reste portable sur Linux ou Raspberry Pi 5.
- **Deux IA** : la vision voit (personnes, zone, badges, caméra), Sentinel Brain décide (capteurs + vision).
- **Socle d'abord** : flux TLS de bout en bout, garde locale, Sentinel Brain couches 1 à 3, vision avec zone. Les extensions (TLS mutuel, badges, détection cyber complète, Réglages, bascule) viennent ensuite.
- **Points de fragilité** : MQTT serveur (Constantin → Lisa), vision (Jeffrick → Momo), storyboard (Constantin), pitch (Jeffrick)."""


def main() -> None:
    plan = yaml.safe_load((ROOT / ".github/kanban/tasks.yml").read_text(encoding="utf-8"))
    team = yaml.safe_load((ROOT / ".github/kanban/team.yml").read_text(encoding="utf-8"))["membres"]
    tasks = plan["taches"]
    out = ["# Répartition de l'équipe — v3 (PC serveur)", "",
           "Généré par `python tools/repartition.py` depuis `.github/kanban/tasks.yml` ; le suivi au jour le jour se "
           "fait dans le Kanban GitHub.", "", "## Décisions qui structurent la répartition", "", DECISIONS, "",
           "## Rôles, binômes et dossiers", "", "| Membre | Compte GitHub | Rôle | Binômes | Dossiers (CODEOWNERS) |",
           "|---|---|---|---|---|"]
    for m in team:
        out.append(f"| {m['prenom']} | `{m['github']}` | {m['role']} | {', '.join(m['binomes'])} | "
                   f"{FOLDERS.get(m['prenom'], '')} |")
    out += ["", "## Charge par personne", "", "| Membre | Tâches | dont bloquantes | faites | Tâches collectives |",
            "|---|---|---|---|---|"]
    collective = [t for t in tasks if t.get("tous")]
    for m in team:
        mine = [t for t in tasks if m["prenom"] in t["assignes"] and not t.get("tous")]
        out.append(f"| {m['prenom']} | {len(mine)} | {sum(t['bloquant'] for t in mine)} | "
                   f"{sum(bool(t.get('fait')) for t in mine)} | {len(collective)} |")

    def row(t, who=None):
        others = [p for p in t["assignes"] if p != who]
        done = " ✅" if t.get("fait") else ""
        return (f"| {t['id']} | {t['titre']}{done} | {t['creneau']} | {t['duree']} | {', '.join(others) or '—'} | "
                f"{'**oui**' if t['bloquant'] else ''} | {t['fini_quand']} |")

    out += ["", "## Tâches collectives", "", "| ID | Tâche | Pilote | Jour | Durée | Bloquant |", "|---|---|---|---|---|---|"]
    for t in collective:
        out.append(f"| {t['id']} | {t['titre']}{' ✅' if t.get('fait') else ''} | {t.get('pilote') or '—'} | "
                   f"{t['jour']} | {t['duree']} | {'oui' if t['bloquant'] else ''} |")
    for m in team:
        out += ["", f"## {m['prenom']}", "", "| ID | Tâche | Créneau | Durée | Avec | Bloquant | Fini quand |",
                "|---|---|---|---|---|---|---|"]
        out += [row(t, m["prenom"]) for t in tasks if m["prenom"] in t["assignes"] and not t.get("tous")]
    out += ["", "## Règles", "", "- Une issue n'est fermée que si sa définition de « fini » est atteinte.",
            "- Les tâches `bloquant` passent avant tout le reste ; les extensions seulement si le socle est stable.",
            "- **Mardi 18 h** : si une vraie mesure de l'ESP32-S3 n'apparaît pas au dashboard en TLS, on arrête les "
            "fonctionnalités et tout le monde aide à l'intégration.", "- Chacun commite lui-même, régulièrement.", ""]
    (ROOT / "docs" / "repartition.md").write_text("\n".join(out), encoding="utf-8")
    print("docs/repartition.md régénéré")


if __name__ == "__main__":
    main()
