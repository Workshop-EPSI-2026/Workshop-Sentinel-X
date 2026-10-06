# Registre des versions — Sentinel-X

> Source unique des versions de l'équipe. **Toute modification passe par une Pull Request.**
> **Politique** : seules les versions publiées avant le **15 août 2026** sont retenues (`EXCLUDE_NEWER` dans
> `tools/lock_deps.py`), pour éviter les versions trop récentes et pas encore éprouvées.
> Contrôle d'un poste : `python tools/doctor.py --role <rôle>` · d'un Pi : `python3 tools/doctor.py --pi`.

## Postes Windows

| Outil | Version | Fixée par |
|---|---|---|
| Python | 3.12.x | `.python-version` |
| Node.js | 22.x (LTS) | `.nvmrc`, installé avec nvm |
| Dépendances Python | versions exactes | `requirements-dev.txt` (généré) |
| Extensions VS Code | liste commune | `.vscode/extensions.json` |
| Règles Python (Ruff 0.16.3) | communes | `ruff.toml` |
| Git, GitHub CLI, VS Code, Docker Desktop | dernière version stable via winget | `tools/setup-poste.ps1` |

## Services (images Docker)

| Composant | Version | Fixée par |
|---|---|---|
| API | FastAPI 0.141.1, Uvicorn 0.52.3, Pydantic 2.13.4, paho-mqtt 2.1.0, psycopg 3.3.4 | `api/requirements.txt` |
| Sentinel Brain | scikit-learn 1.9.0, numpy 2.5.2, statsmodels 0.14.6 | `ai/anomaly/requirements.txt` |
| Vision | Ultralytics 8.4.120, NCNN 1.0.20260526, OpenCV 4.14.0.94, PyTorch 2.13.0 (CPU) | `ai/vision/requirements.txt`, `ai/vision/torch-cpu.txt` |
| Simulateur | paho-mqtt 2.1.0 | `tools/requirements.txt` |
| Images de base | `eclipse-mosquitto:2.0`, `postgres:16-alpine`, `nginxinc/nginx-unprivileged:1.27-alpine`, `python:3.12-slim` | `infra/docker-compose.yml`, `Dockerfile` — **empreintes à relever lundi** |

## À relever lundi (première installation)

| Élément | Valeur | Qui |
|---|---|---|
| Image Raspberry Pi OS (nom du fichier, date) | | Michel |
| Docker Engine sur les deux Pi (`docker version`) | | Michel |
| Empreintes des images Docker | | Constantin |
| Plateforme PlatformIO `espressif32@` et bibliothèques | | Momo |
| Modèle `yolov8n_ncnn_model` (SHA-256 du dossier zippé) | | Jeffrick |

### Épingler les images Docker par empreinte (sur le Pi 5)

```bash
docker pull eclipse-mosquitto:2.0 && docker pull postgres:16-alpine
docker pull nginxinc/nginx-unprivileged:1.27-alpine && docker pull python:3.12-slim
for i in eclipse-mosquitto:2.0 postgres:16-alpine nginxinc/nginx-unprivileged:1.27-alpine python:3.12-slim; do
  docker image inspect --format '{{index .RepoDigests 0}}' "$i"
done
```

Remplacer ensuite chaque image par `nom:tag@sha256:...` dans `infra/docker-compose.yml` et les `FROM` des
`Dockerfile`. L'empreinte relevée est celle de l'index multi-architecture : elle vaut pour le Pi (arm64) comme pour
les postes (amd64).

### Empreinte du modèle de vision

```bash
cd ai/vision/models && zip -qr yolov8n_ncnn_model.zip yolov8n_ncnn_model && sha256sum yolov8n_ncnn_model.zip
```

Le zip est partagé hors Git (clé USB, dossier partagé) ; chacun vérifie l'empreinte avant de l'utiliser.

## Mettre à jour une dépendance Python

1. Modifier la plage dans le `requirements.in` concerné.
2. Régénérer : `pip install uv==0.11.7` puis `python tools/lock_deps.py`.
3. Pull Request ; la CI vérifie que les verrous sont à jour (`python tools/lock_deps.py --check`).
4. Chacun réinstalle : `pip install -r requirements-dev.txt`, puis `python tools/doctor.py`.
