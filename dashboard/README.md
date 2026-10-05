# Dashboard — Constantin (binôme graphiques et jauge Sentinel Score : Jeffrick)

Compilé **sur un laptop** (`npm run build`), jamais de serveur de développement sur le Pi.
`dist/` est servi par nginx : `scp -r dist sentinel-pi:~/Workshop-Sentinel-X/dashboard/`.

## Vues
| Vue | Contenu |
| --- | --- |
| Supervision | Jauge Sentinel Score (global + environnement / physique / cyber), courbes live, voyant du boîtier, mode |
| Incidents | Liste par gravité, explication et facteurs, prévision « critique dans N min », acquitter / résoudre |
| Vision | Flux `/video` annoté, zone, FPS, latence |
| Système | Santé du Pi et des boîtiers (RSSI, mémoire, tampon, température), état de chaque conteneur |
| Réglages | Profil de site : sensibilités, seuils, modes et horaires, zone de la caméra (`GET/PUT /api/v1/config`) |

Temps réel par `wss://<pi>/ws`, même origine que l'API (pas de CORS). Grosses polices et forts contrastes pour la salle et Teams.
