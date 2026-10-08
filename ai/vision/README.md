# Vision (`ai/vision`) — tâche je1, Jeffrick (binôme : Momo)

Sous Windows, Docker Desktop ne donne pas accès à la webcam : **la vision tourne directement sur le PC serveur**,
dans le `.venv` (installé sur tous les postes par `installer.cmd`). `tools\demarrer.ps1` la lance avec le reste.
Sous Linux ou sur un Raspberry Pi, le même code tourne dans un conteneur (`infra/docker-compose.linux.yml`).

| Fichier | Rôle |
| --- | --- |
| `app/analysis.py` | Zone (point des pieds dans le polygone), intégrité (masquée / sombre), mouvement (MOG2), badges ArUco, présence par personne |
| `app/detector.py` | YOLOv8n + ByteTrack, classe personne |
| `app/pipeline.py` | Une image → état (personnes, zone, badges, intégrité) + image annotée |
| `app/service.py` | Capture, publication MQTT `sentinel/cam-01/vision`, serveur HTTP `/health`, `/video`, `/snapshot.jpg` |
| `app/main.py` | Point d'entrée |
| `tools/demo_video.py` | Vidéo de démonstration sans webcam (agent badgé, intrus, masquage, obscurité) : tests et plan B |
| `tools/badges.py` | Badges ArUco à imprimer pour les agents autorisés |
| `tools/benchmark.py` | Mesure YOLO (tâche j2) → `docs/preuves/latence-yolo.md` |
| `tests/test_vision.py` | Tests sans webcam (YOLO réel si `models/yolov8n.pt` est présent) |

## Commandes (depuis `ai\vision`, `.venv` activé)

```powershell
python -m app.main --env ..\..\infra\.env                  # webcam 0, broker du .env (1883 ou 8883 TLS)
python -m app.main --no-mqtt                               # vision seule : régler la zone sur http://127.0.0.1:8001/video
python tools\demo_video.py                                 # -> data\demo.mp4
python -m app.main --env ..\..\infra\.env --source data\demo.mp4
python tools\badges.py 7 12                                # -> data\badges\badge-07.png (imprimer à 6 cm)
python tools\benchmark.py                                  # tableau de latence (tâche j2)
python tools\visages.py modeles                            # YuNet + SFace (37 Mo) dans models\
python tools\visages.py enroler C:\photos                  # un sous-dossier par personne : C:\photos\Michel\*.jpg
python tools\visages.py tester                             # fiabilité de la galerie (validation croisée)
python tools\visages.py oublier Michel                     # retire une personne (droit à l'effacement)
python -m unittest discover -s tests -v
```

Le modèle `yolov8n.pt` (6 Mo) est téléchargé dans `models\` par `installer.cmd`. Une fois présent,
la vision ne contacte plus Internet (`YOLO_OFFLINE`). Sur Raspberry Pi : `python tools\benchmark.py --ncnn` crée
`yolov8n_ncnn_model`, 2 à 3 fois plus rapide sur processeur ARM (`VISION_MODEL=yolov8n_ncnn_model`).

## Règles (profil de site, section `vision`)

- **Zone** : polygone normalisé ; une personne est « dans la zone » quand ses pieds y sont.
- **Badges** : `authorized_badges` (id, nom, horaires). La vision lit le badge et le garde pendant tout le suivi de la
  personne ; **Brain décide** avec les horaires (agent autorisé, présence à vérifier, intrus accompagné).
- **Visages** : `authorized_faces` (nom, horaires), avec l'accord écrit des personnes. `visages.py enroler` garde
  seulement des vecteurs de 128 nombres (`data\visages.npz`, hors dépôt), **jamais les photos**. Seuls les visages
  de face sont comparés (de profil, deux personnes se ressemblent trop) ; une identité est confirmée après deux
  reconnaissances concordantes, puis revérifiée toutes les 5 s. Comme pour un badge, **Brain décide** avec les
  horaires. Sans modèles ou sans galerie, la vision tourne normalement sans reconnaissance (`VISION_FACES=0` pour
  la couper). Mesure sur les photos de l'équipe (Michel, Jeffrick ; webcam du PC) : 42 visages de face sur 45
  reconnus, **aucune confusion** entre les deux, similarité maximale entre eux 0,35 pour un seuil de 0,45 ; 20 à
  40 ms par visage, au plus un par image.
  **Limite** : une photo du visage tenue devant la caméra peut tromper SFace (pas de détection du vivant) : un
  visage reconnu reste un indice, comme un badge photocopié ; le PIR, les horaires et le mode maintenance restent
  croisés par Brain.
- **Intégrité** : image uniforme ou noire 2 s = caméra masquée (sabotage) ; image sombre mais texturée 3 s = faible
  luminosité (le PIR prend le relais) ; image strictement identique 10 s = flux figé.
- **Économie** : YOLO ne tourne que s'il y a du mouvement, une personne récente, ou une image sur 10.

Mesures sur le PC de développement (processeur Xeon 2,1 GHz, 2 cœurs) : YOLOv8n PyTorch **38 ms à 320 px**
(26 images/s), 123 ms à 640 px. Le PC serveur de la démo doit être mesuré avec `tools\benchmark.py`.
