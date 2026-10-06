# Dashboard — Constantin (binôme graphiques et jauge Sentinel Score : Jeffrick)

Compilé avec `npm run build` (sur le PC serveur ou un laptop), jamais de serveur de développement pendant la démo.
`dist/` est servi par nginx depuis `dashboard/dist` du dépôt cloné sur le PC serveur (y copier le dossier s'il est compilé ailleurs).

## Vues
| Vue | Contenu |
| --- | --- |
| Supervision | Jauge Sentinel Score (global + environnement / physique / cyber), courbes live, voyant du boîtier, mode |
| Incidents | Liste par gravité, explication et facteurs, prévision « critique dans N min », acquitter / résoudre |
| Vision | Flux `/video` annoté, zone, FPS, latence |
| Système | Santé du serveur et des boîtiers (RSSI, mémoire, tampon, température), état de chaque conteneur |
| Réglages | Profil de site : sensibilités, seuils, modes et horaires, zone de la caméra (`GET/PUT /api/v1/config`) |

Temps réel par `wss://<serveur>/ws`, même origine que l'API (pas de CORS). Grosses polices et forts contrastes pour la salle et Teams.
