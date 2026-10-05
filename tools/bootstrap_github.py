#!/usr/bin/env python3
"""
Sentinel-X — création du dépôt GitHub et du Kanban à partir du plan d'équipe.

Prérequis (sur le poste de Constantin) :
  - GitHub CLI installé et connecté :   gh auth login
  - droit "project" pour le Kanban :    gh auth refresh -s project
  - Python 3 + PyYAML :                 pip install pyyaml
  - les comptes GitHub renseignés dans  .github/kanban/team.yml

Usage (depuis la racine du dépôt) :
  python3 tools/bootstrap_github.py --dry-run          # affiche ce qui serait fait
  python3 tools/bootstrap_github.py                    # crée tout
  python3 tools/bootstrap_github.py --assign-only      # plus tard : assigne les issues
                                                       # aux membres ayant accepté l'invitation
  python3 tools/bootstrap_github.py --sync             # après modification de tasks.yml : met à jour
                                                       # titres, contenus, labels, jalons ; crée les
                                                       # nouvelles tâches et les ajoute au Kanban
Options : --owner <compte ou organisation>  --name <nom du dépôt>  --public  --no-project
"""
import argparse, json, pathlib, subprocess, sys

try:
    import yaml
except ImportError:
    sys.exit("PyYAML manquant : pip install pyyaml")

ROOT = pathlib.Path(__file__).resolve().parent.parent
TEAM = ROOT / ".github/kanban/team.yml"
TASKS = ROOT / ".github/kanban/tasks.yml"
CODEOWNERS = ROOT / ".github/CODEOWNERS"
DRY = False


def run(cmd, input=None, check=True, quiet=False):
    """Exécute une commande (ou l'affiche seulement en --dry-run)."""
    if DRY and cmd[0] in ("gh", "git") and cmd[:2] not in (["gh", "auth"],) and "view" not in cmd and "list" not in cmd:
        print("  [dry-run]", " ".join(cmd))
        return ""
    try:
        r = subprocess.run(cmd, input=input, text=True, capture_output=True, cwd=ROOT)
    except FileNotFoundError:
        if DRY:
            return None
        sys.exit(f"Commande introuvable : {cmd[0]}. Installer GitHub CLI : https://cli.github.com")
    if check and r.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)}\n{r.stderr.strip()}")
    if not quiet and r.stderr.strip() and r.returncode != 0:
        print("  !", r.stderr.strip())
    return r.stdout.strip() if r.returncode == 0 else None


def step(t):
    print(f"\n== {t}")


def main():
    global DRY
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--owner", help="compte ou organisation GitHub (défaut : compte connecté)")
    ap.add_argument("--name", default="sentinel-x")
    ap.add_argument("--public", action="store_true", help="dépôt public (défaut : privé)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--assign-only", action="store_true")
    ap.add_argument("--sync", action="store_true", help="mettre à jour les issues existantes depuis tasks.yml")
    ap.add_argument("--no-project", action="store_true", help="ne pas créer le Kanban GitHub Projects")
    a = ap.parse_args()
    DRY = a.dry_run

    team = yaml.safe_load(TEAM.read_text(encoding="utf-8"))["membres"]
    plan = yaml.safe_load(TASKS.read_text(encoding="utf-8"))
    handles = {m["prenom"]: m["github"] for m in team}
    missing = [p for p, h in handles.items() if not h or h == "A_RENSEIGNER"]
    if missing and not DRY:
        sys.exit(f"Renseigner le compte GitHub de : {', '.join(missing)} dans {TEAM.relative_to(ROOT)}")
    if missing:
        handles = {p: (h if h != "A_RENSEIGNER" else f"<{p.lower()}>") for p, h in handles.items()}

    if run(["gh", "auth", "status"], check=False, quiet=True) is None and not DRY:
        sys.exit("GitHub CLI non connecté : lancer  gh auth login")
    me = run(["gh", "api", "user", "--jq", ".login"], check=False, quiet=True) or "<moi>"
    owner = a.owner or me
    repo = f"{owner}/{a.name}"
    print(f"Dépôt cible : {repo}  ({'public' if a.public else 'privé'})")

    if a.assign_only:
        assign_existing(repo, plan, handles)
        return
    if a.sync:
        sync(repo, owner, plan, handles, not a.no_project)
        return

    # 1. CODEOWNERS --------------------------------------------------------
    step("CODEOWNERS : remplacement des comptes")
    txt = CODEOWNERS.read_text(encoding="utf-8")
    for p, h in handles.items():
        txt = txt.replace(f"@gh-{p.lower()}", f"@{h}")
    if DRY:
        print("  [dry-run] .github/CODEOWNERS mis à jour")
    else:
        CODEOWNERS.write_text(txt, encoding="utf-8")

    # 2. Git local ---------------------------------------------------------
    step("Dépôt Git local")
    if not (ROOT / ".git").exists():
        run(["git", "init", "-b", "main"])
    run(["git", "add", "-A"])
    if DRY or run(["git", "status", "--porcelain"], check=False):
        run(["git", "commit", "-m", "chore: initialisation du dépôt Sentinel-X"], check=False)

    # 3. Dépôt GitHub ------------------------------------------------------
    step("Dépôt GitHub")
    exists = run(["gh", "repo", "view", repo, "--json", "name"], check=False, quiet=True)
    if exists:
        print("  existe déjà : simple push")
        run(["git", "push", "-u", "origin", "main"], check=False)
    else:
        run(["gh", "repo", "create", repo, "--public" if a.public else "--private", "--source", ".",
             "--remote", "origin", "--push",
             "--description", "Mission Sentinel-X — boîtier de surveillance IoT/IA sécurisé (Workshop M1 EPSI 2026)"])

    # 4. Membres -----------------------------------------------------------
    step("Invitation des membres (droit d'écriture)")
    for p, h in handles.items():
        if h == me:
            continue
        r = run(["gh", "api", "-X", "PUT", f"repos/{repo}/collaborators/{h}", "-f", "permission=push"], check=False)
        print(f"  {p} ({h}) : {'invité' if r is not None else 'échec'}")

    # 5. Labels ------------------------------------------------------------
    step("Labels")
    for l in plan["labels"]:
        run(["gh", "label", "create", l["nom"], "-R", repo, "--color", l["couleur"],
             "--description", l["description"], "--force"], check=False)
    print(f"  {len(plan['labels'])} labels")

    # 6. Jalons (un par jour) ---------------------------------------------
    step("Jalons")
    have = set((run(["gh", "api", f"repos/{repo}/milestones?state=all", "--jq", ".[].title"],
                    check=False, quiet=True) or "").splitlines())
    for j in plan["jalons"]:
        if j["titre"] not in have:
            run(["gh", "api", f"repos/{repo}/milestones", "-f", f"title={j['titre']}",
                 "-f", f"description={j['description']}"], check=False)
    print(f"  {len(plan['jalons'])} jalons")

    # 7. Issues ------------------------------------------------------------
    step("Issues (une par tâche du plan)")
    existing = issues_by_id(repo)
    urls, not_assigned = [], []
    for t in plan["taches"]:
        if t["id"] in existing:
            urls.append(existing[t["id"]]["url"])
            continue
        title = f"[{t['id']}] {t['titre']}"
        base = ["gh", "issue", "create", "-R", repo, "--title", title, "--body", body(t),
                "--milestone", t["jour"]]
        for l in t["labels"]:
            base += ["--label", l]
        who = [handles[p] for p in t["assignes"]]
        url = run(base + ["--assignee", ",".join(who)], check=False, quiet=True)
        if url is None and not DRY:
            url = run(base, check=False)          # membre pas encore dans le dépôt : sans assignation
            not_assigned.append(t["id"])
        if url:
            urls.append(url)
            if t.get("fait"):
                run(["gh", "issue", "close", url, "--reason", "completed"], check=False)
        print(f"  {title}")
    if not_assigned:
        print(f"\n  ⚠ {len(not_assigned)} issues non assignées (invitations en attente). "
              "Quand tout le monde a accepté : python3 tools/bootstrap_github.py --assign-only")

    # 8. Protection de main ------------------------------------------------
    step("Protection de la branche main")
    rule = {"required_status_checks": None, "enforce_admins": False,
            "required_pull_request_reviews": {"required_approving_review_count": 1,
                                              "require_code_owner_reviews": False,
                                              "dismiss_stale_reviews": False},
            "restrictions": None, "allow_force_pushes": False, "allow_deletions": False}
    r = run(["gh", "api", "-X", "PUT", f"repos/{repo}/branches/main/protection", "--input", "-"],
            input=json.dumps(rule), check=False)
    if r is None and not DRY:
        print("  ⚠ Refusé par GitHub. Pour un dépôt privé, il faut GitHub Pro (gratuit avec le Student "
              "Developer Pack) ou une organisation GitHub Team. Sinon : règle d'équipe « pas de push direct sur main ».")

    # 9. Kanban GitHub Projects -------------------------------------------
    if not a.no_project:
        step("Kanban (GitHub Projects)")
        num = run(["gh", "project", "create", "--owner", owner, "--title", "Sentinel-X — Kanban",
                   "--format", "json", "--jq", ".number"], check=False)
        if num is None and not DRY:
            print("  ⚠ Échec : lancer  gh auth refresh -s project  puis relancer le script, "
                  "ou créer le projet à la main (voir README).")
        else:
            num = num or "<n>"
            run(["gh", "project", "link", str(num), "--owner", owner, "--repo", a.name], check=False)
            for u in urls:
                run(["gh", "project", "item-add", str(num), "--owner", owner, "--url", u], check=False, quiet=True)
            print(f"  projet n°{num} : {len(urls)} cartes ajoutées. Ajouter la colonne « En revue » "
                  "dans le champ Status depuis l'interface (voir README).")

    print("\nTerminé. Chaque membre peut maintenant : accepter l'invitation, puis  git clone",
          f"https://github.com/{repo}.git")


def issues_by_id(repo):
    out = run(["gh", "issue", "list", "-R", repo, "--state", "all", "--limit", "300",
               "--json", "number,title,url"], check=False, quiet=True)
    res = {}
    for i in json.loads(out or "[]"):
        if i["title"].startswith("[") and "]" in i["title"]:
            res[i["title"][1:i["title"].index("]")]] = i
    return res


def assign_existing(repo, plan, handles):
    step("Assignation des issues existantes")
    existing = issues_by_id(repo)
    for t in plan["taches"]:
        i = existing.get(t["id"])
        if not i:
            continue
        who = ",".join(handles[p] for p in t["assignes"])
        r = run(["gh", "issue", "edit", str(i["number"]), "-R", repo, "--add-assignee", who], check=False)
        print(f"  #{i['number']} [{t['id']}] -> {who} {'' if r is not None or DRY else '(échec)'}")


def sync(repo, owner, plan, handles, with_project):
    step("Labels et jalons")
    for l in plan["labels"]:
        run(["gh", "label", "create", l["nom"], "-R", repo, "--color", l["couleur"],
             "--description", l["description"], "--force"], check=False)
    have = set((run(["gh", "api", f"repos/{repo}/milestones?state=all", "--jq", ".[].title"],
                    check=False, quiet=True) or "").splitlines())
    for j in plan["jalons"]:
        if j["titre"] not in have:
            run(["gh", "api", f"repos/{repo}/milestones", "-f", f"title={j['titre']}",
                 "-f", f"description={j['description']}"], check=False)
    step("Issues : mise à jour et nouvelles tâches")
    existing = issues_by_id(repo)
    new_urls = []
    for t in plan["taches"]:
        title = f"[{t['id']}] {t['titre']}"
        if t["id"] in existing:
            cmd = ["gh", "issue", "edit", str(existing[t["id"]]["number"]), "-R", repo,
                   "--title", title, "--body", body(t), "--milestone", t["jour"]]
            for l in t["labels"]:
                cmd += ["--add-label", l]
            r = run(cmd, check=False)
            print(f"  mis à jour  {title}" + ("" if r is not None or DRY else "  (échec)"))
        else:
            base = ["gh", "issue", "create", "-R", repo, "--title", title, "--body", body(t),
                    "--milestone", t["jour"]]
            for l in t["labels"]:
                base += ["--label", l]
            url = run(base + ["--assignee", ",".join(handles[p] for p in t["assignes"])], check=False, quiet=True)
            if url is None and not DRY:
                url = run(base, check=False)
            if url:
                new_urls.append(url)
            print(f"  créé        {title}")
    if with_project and new_urls:
        step("Ajout des nouvelles tâches au Kanban")
        out = run(["gh", "project", "list", "--owner", owner, "--format", "json"], check=False, quiet=True)
        num = None
        for pr in json.loads(out or "{}").get("projects", []):
            if pr.get("title") == "Sentinel-X — Kanban":
                num = pr.get("number")
        if num is None and not DRY:
            print("  ⚠ Projet « Sentinel-X — Kanban » introuvable : ajouter les nouvelles issues à la main.")
        else:
            for u in new_urls:
                run(["gh", "project", "item-add", str(num or "<n>"), "--owner", owner, "--url", u], check=False, quiet=True)
            print(f"  {len(new_urls)} carte(s) ajoutée(s)")
    print("\nSynchronisation terminée.")


def body(t):
    equipe = ", ".join(f"{p} (pilote)" if p == t.get("pilote") else p for p in t["assignes"])
    lines = [f"**Créneau :** {t['creneau']} · **Durée :** {t['duree']} · "
             f"**Bloquant :** {'oui' if t['bloquant'] else 'non'}",
             f"**Équipe :** {'toute l’équipe' + (' — pilote : ' + t['pilote'] if t.get('pilote') else '') if t['tous'] else equipe}",
             "", "### À faire"]
    lines += [f"- [ ] {d}" for d in t["detail"]]
    lines += ["", "### Fini quand", t["fini_quand"], "",
              f"<sub>Tâche `{t['id']}` du plan d'équipe — source : `.github/kanban/tasks.yml`</sub>"]
    return "\n".join(lines)


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as e:
        sys.exit(f"\nErreur :\n{e}")
