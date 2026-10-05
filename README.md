# Sentinel-X

> Workshop M1 EPSI 2026 · Mission Sentinel-X pour AetherCorp Industrial Solutions.
> Boîtier de surveillance autonome : ESP32-S3 et capteurs, Raspberry Pi 5 embarqué (Option A, Pi 4 en repli),
> détection multicouche (environnement, intrusion, cyber), flux chiffrés de bout en bout.

## Équipe

| Membre | Rôle |
|---|---|
| Constantin | Lead intégration · Backend · Stack Docker sur le Pi · Dashboard |
| Jeffrick | Lead IA et data · Anomalies · Vision · BDD · Pitch |
| Momo | Lead embarqué · Firmware ESP32-S3 · Câblage |
| Lisa | Lead cybersécurité · PKI · Hardening · Audit · Dossier |
| Michel | Raspberry Pi et réseau de table · Matériel · Fablab · Vidéo |

Répartition détaillée, binômes et charge : [`docs/repartition.md`](docs/repartition.md).

## Installer le même environnement sur tous les postes

Tout le monde part du même dépôt et obtient les mêmes versions. Deux chemins : automatique (poste neuf) ou
manuel (si Python, Git et VS Code sont déjà là). Le registre des versions est [`VERSIONS.md`](VERSIONS.md) ;
la vérification d'un poste est `python tools/doctor.py`.

### 0. Prérequis une seule fois : cloner

```powershell
git clone https://github.com/Workshop-EPSI-2026/Workshop-Sentinel-X.git
cd Workshop-Sentinel-X
```

### Chemin A — installation automatique (recommandé)

Une commande installe les logiciels (winget), Node.js, les extensions VS Code, règle Git, crée la clé SSH
et l'environnement Python aux versions exactes, puis contrôle le poste. Remplacer `<rôle>` par le vôtre :
`ia` (Jeffrick), `iot` (Momo, Michel), `cyber` (Lisa), `integration` (Constantin), `fablab` (Michel).

```powershell
powershell -ExecutionPolicy Bypass -File tools\setup-poste.ps1 -Role <rôle>
```

Fermer puis rouvrir PowerShell si le script le demande (après l'installation de Node ou de VS Code), et le
relancer : il reprend là où il en était. À la fin, il affiche le contrôle du poste.

### Chemin B — installation manuelle

1. Installer les logiciels de base (si absents) :

```powershell
winget install --id Git.Git -e
winget install --id GitHub.cli -e
winget install --id Microsoft.VisualStudioCode -e
winget install --id Python.Python.3.12 -e
winget install --id CoreyButler.NVMforWindows -e
winget install --id Docker.DockerDesktop -e
```

   Fermer et rouvrir PowerShell, puis Node à la version du dépôt :

```powershell
nvm install 22
nvm use 22
```

   Clients Mosquitto : installateur Windows 64 bits depuis https://mosquitto.org/download/, puis ajouter
   `C:\Program Files\mosquitto` au `Path`.

2. Régler Git, créer la clé SSH :

```powershell
git config --global core.autocrlf false
git config --global init.defaultBranch main
git config --global user.name "Prénom Nom"
git config --global user.email "adresse-du-compte-github"
ssh-keygen -t ed25519 -C "prenom@sentinel"
```

3. Créer l'environnement Python aux versions exactes :

```powershell
py -3.12 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
```

4. Outils du rôle en plus :

| Rôle | Commandes supplémentaires |
|---|---|
| `ia` | `pip install -r ai\vision\torch-cpu.txt --index-url https://download.pytorch.org/whl/cpu` puis `pip install -r ai\vision\requirements.txt` |
| `iot` | Extension PlatformIO : `code --install-extension platformio.platformio-ide` |
| `cyber` | `winget install --id Insecure.Nmap -e` et `winget install --id WiresharkFoundation.Wireshark -e` ; Metasploit s'installe sur la station d'audit (Pi 4 : `sudo apt install metasploit-framework`) |
| `integration` | `winget install --id OBSProject.OBSStudio -e` |
| `fablab` | `winget install --id RaspberryPiFoundation.RaspberryPiImager -e` |

### Contrôler son poste

```powershell
python tools\doctor.py --role <rôle>
```

Objectif : aucune ligne `[KO]`. Chaque ligne en défaut indique la commande de correction. `[!!]` signale un
point à surveiller sans gravité.

### Chaque jour

```powershell
cd Workshop-Sentinel-X
.venv\Scripts\activate
git switch main
git pull
```

Si `git pull` a modifié un fichier `requirements*.txt` : `pip install -r requirements-dev.txt`.

### Sur les Raspberry Pi

Pas de `.venv` : les services tournent dans Docker, aux versions figées. Après le clone :

```bash
python3 tools/doctor.py --pi
cd infra && docker compose build && docker compose up -d
```

### Ajouter une bibliothèque Python

Ne jamais modifier un `requirements.txt` à la main (il est généré). Modifier le `requirements.in` concerné, puis :

```powershell
pip install "uv==0.11.7"
python tools\lock_deps.py
pip install -r requirements-dev.txt
```

Commiter les `.in` et les `.txt` ensemble, par Pull Request. La CI refuse un `.in` modifié sans régénération.

## Architecture v2



Référence complète : [`docs/architecture.md`](docs/architecture.md).

```
ESP32-S3 N16R8 + DHT11 / MQ-2 / PIR / effraction tactile
   garde locale, alarme réflexe, tampon PSRAM, voyant RGB
        │  Wi-Fi WPA2 (point d'accès du Pi 5) · MQTTS 8883 (TLS mutuel en cible)
        ▼
Raspberry Pi 5 (sentinel-pi, 192.168.10.1) — Docker Compose      Pi 4 (192.168.10.2) : repli + audit
  ├─ mosquitto   8883 boîtiers [publié] · 8884 services [interne]
  ├─ api         REST, WebSocket, incidents, profil de site
  ├─ postgres    historique (réseau interne)
  ├─ vision      YOLO NCNN, suivi, zone, caméra masquée, /video
  ├─ anomaly     Sentinel Brain : 4 couches + fusion + score expliqué
  └─ nginx       HTTPS/WSS + dashboard                         [publié : 443]
```

Contrat : [`docs/contracts.md`](docs/contracts.md) · Câblage : [`docs/cablage.md`](docs/cablage.md) ·
Réseau : [`docs/reseau.md`](docs/reseau.md) · Sécurité : [`docs/securite.md`](docs/securite.md) ·
Profil de site : [`config/site.example.yml`](config/site.example.yml).

## Arborescence

| Dossier | Contenu | Propriétaire |
|---|---|---|
| `firmware/` | Firmware ESP32-S3 (PlatformIO), brochage `pins.h` | Momo |
| `config/` | Profils de site (personnalisation) | Constantin, Jeffrick |
| `api/` | API REST + WebSocket | Constantin |
| `dashboard/` | Interface web (compilée sur laptop) | Constantin |
| `ai/vision/`, `ai/anomaly/` | Vision et Sentinel Brain | Jeffrick |
| `infra/` | `docker-compose.yml`, Mosquitto, nginx, init PostgreSQL | Constantin, Michel |
| `security/` | PKI (sans clés), hardening, audits | Lisa |
| `docs/` | Contrat, réseau, câblage, fablab, preuves, dossier | Tous |
| `tools/` | Création du dépôt, simulateur d'ESP | Constantin, Jeffrick |
| `.github/` | CI, modèles d'issues et de PR, CODEOWNERS, plan du Kanban | Constantin |

## Démarrer la stack (sur le Pi 5, ou le Pi 4 de repli)

```bash
git clone <url-du-dépôt> sentinel-x && cd sentinel-x/infra
cp .env.example .env             # remplir toutes les valeurs CHANGE_ME
# créer infra/mosquitto/passwd : voir infra/mosquitto/README.md
docker compose up -d             # lundi : mosquitto + postgres, MQTT 1883 authentifié
docker compose ps                # tous les services doivent être "healthy"
```

Progression dans `infra/.env` :

| Moment | `COMPOSE_FILE` | `MQTT_PORT` / `MQTT_TLS` | `COMPOSE_PROFILES` |
|---|---|---|---|
| Lundi | `docker-compose.yml:docker-compose.dev.yml` | `1883` / `false` | *(vide)* |
| Dès que l'API existe | idem | idem | `app` |
| Mardi, après les certificats de Lisa | `docker-compose.yml` | `8884` / `true` | `app` |
| Dès que les services IA existent | `docker-compose.yml` | `8884` / `true` | `app,ai` |
| TLS mutuel prêt | idem, avec `MOSQUITTO_CONF=mosquitto.mtls.conf` | `8884` / `true` | `app,ai` |

Puis `docker compose up -d --build` à chaque changement.

## Règles Git de l'équipe

1. **`main` est toujours démontrable.** Jamais de push direct : une branche par tâche, puis une Pull Request.
2. **Branches** : `feat/<brique>-<sujet>`, `fix/<sujet>`, `docs/<sujet>` (ex. `feat/firmware-tls`).
3. **Commits** : `type(brique): message` — types `feat`, `fix`, `docs`, `sec`, `refactor`, `chore`
   (ex. `feat(api): validation stricte de POST /alerts`).
4. **PR** : relue par au moins un membre (les propriétaires du dossier sont demandés automatiquement), CI verte, issue liée avec `Closes #n`.
5. **Aucun secret** dans le dépôt : `.env`, `secrets.h`, `passwd`, `security/certs/` sont ignorés ; gitleaks tourne en CI.
6. **Chacun commite lui-même, souvent** : l'historique sert aussi à la note individuelle.
7. **Jalons** : `v0.1-poc` (mardi soir), `v0.2-integration` (mercredi), `v1.0` (gel du code jeudi matin).

```bash
git switch -c feat/api-alerts
git add -p && git commit -m "feat(api): POST /api/v1/alerts avec validation"
git push -u origin feat/api-alerts
gh pr create --fill              # ou depuis l'interface GitHub
```

## Kanban

Les tâches du plan d'équipe sont décrites dans `.github/kanban/tasks.yml` et deviennent des
issues GitHub (une par tâche, avec responsables, jalon du jour, labels de brique et `bloquant`,
cases à cocher et définition de « fini »). Colonnes : **À faire → En cours → En revue → Terminé**,
une seule carte « En cours » par personne.

## Création du dépôt (une seule fois)

**Automatique** (recommandé) — sur un poste avec [GitHub CLI](https://cli.github.com) :
```bash
gh auth login && gh auth refresh -s project
pip install pyyaml
# renseigner les comptes GitHub dans .github/kanban/team.yml
python3 tools/bootstrap_github.py --dry-run     # vérifier
python3 tools/bootstrap_github.py               # créer
# quand tout le monde a accepté l'invitation :
python3 tools/bootstrap_github.py --assign-only
# après une mise à jour de tasks.yml (titres, contenus, nouvelles tâches) :
python3 tools/bootstrap_github.py --sync
```
Le script crée le dépôt privé, pousse ce squelette, invite les 4 autres membres, crée labels,
jalons, les issues, la protection de `main` et le projet Kanban.

**Manuelle** — sur github.com : *New repository* `sentinel-x` (privé, sans README), puis :
```bash
git init -b main && git add -A && git commit -m "chore: initialisation du dépôt Sentinel-X"
git remote add origin https://github.com/<compte>/sentinel-x.git && git push -u origin main
```
Puis *Settings → Collaborators* (inviter les 4 membres), *Settings → Branches* (protéger `main`),
*Projects → New project → Board*, et remplacer les `@gh-<prénom>` de `.github/CODEOWNERS`.

## Livrables

Rapport technique (PDF) · Vidéo « Sentinel Drop » (`Workshop2026-M1-G<n>-VidDrop.mp4`) ·
Archive du code (zip du tag `v1.0`) · Support de soutenance (`Workshop2026-M1-G<n>-Pres.pptx`) ·
Sentinel-X fonctionnel.
