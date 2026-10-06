# Dashboard — Constantin (binôme graphiques et jauge Sentinel Score : Jeffrick)

Compilé sur le PC serveur ou sur un poste (`npm run build`, Node 22). `dist/` est servi par nginx (conteneur `nginx`,
monté depuis `dashboard/dist`) : sur le PC serveur, il suffit de compiler puis `docker compose restart nginx`.
Sur un autre poste : copier `dist/` dans `dashboard/dist` du PC serveur (clé USB ou `git pull` d'une branche de build).

## Vues
| Vue | Contenu |
| --- | --- |
| Supervision | Jauge Sentinel Score (global + environnement / physique / cyber), courbes live, voyant du boîtier, mode |
| Incidents | Liste par gravité, explication et facteurs, prévision « critique dans N min », acquitter / résoudre |
| Vision | Flux `/video` annoté (zone, personnes, badges), FPS, personnes dans la zone, état de la caméra |
| Système | Santé du PC serveur et des boîtiers (RSSI, mémoire, tampon, température), état de chaque conteneur et de la vision (`/vision/health`) |
| Réglages | Profil de site : sensibilités, seuils, modes et horaires, zone de la caméra, badges autorisés (`GET/PUT /api/v1/config`) |

Temps réel par `wss://<serveur>/ws`, même origine que l'API (pas de CORS). Le certificat est celui de la CA locale :
l'importer une fois dans Windows (*Gérer les certificats*, Autorités de certification racines) pour éviter
l'avertissement du navigateur. Grosses polices et forts contrastes pour la salle et Teams.
