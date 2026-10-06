# Dashboard — Constantin (binôme graphiques et jauge Sentinel Score : Jeffrick)

React + TypeScript + Vite, sans bibliothèque de graphiques (SVG maison). Compilé avec `npm run build` en fichiers
statiques dans `dist/`, servis par nginx sur le PC serveur. Jamais de serveur de développement pendant la démo.

## Démarrer

```powershell
cd dashboard
npm install
npm run dev          # http://localhost:5173 ; /api, /ws et /video relayés vers https://localhost (nginx)
npm run build        # dist/ servi par nginx : https://192.168.137.1 (ou https://localhost sur le PC serveur)
npm test             # état temps réel, libellés, client de l'API (jeton jamais dans une URL)
```

Pour viser un autre serveur pendant le développement : `$env:VITE_API_TARGET="https://192.168.137.1"; npm run dev`.

## Brancher sur l'API réelle

L'API tourne dans Docker et n'est joignable que par nginx (HTTPS sur le PC serveur). Deux façons de développer :

- **Avec la pile Docker complète** : `cd infra; docker compose up -d --build` (profil `app`, certificats prêts), puis
  `npm run dev` : le relais Vite vise `https://localhost` (nginx) par défaut.
- **Sans nginx, avec l'API lancée à la main** (voir `api/README.md`, `python dev.py`) :
  ```powershell
  $env:VITE_API_TARGET="http://127.0.0.1:8000"; npm run dev
  ```

Sur l'écran de connexion, saisir `OPERATOR_TOKEN` (`infra/.env`). Vérifié de bout en bout dans Chrome (connexion,
mesures en direct du simulateur, incident reçu sans recharger, acquittement, commande, enregistrement des réglages,
reconnexion automatique quand l'API redémarre).

## Mode démo (sans API)

Bouton **Mode démo** sur l'écran de connexion, ou lien direct `/?demo`. Le simulateur (`src/api/demo.ts`) produit le
boîtier `esp-01`, Sentinel Brain et les incidents au format exact du contrat, avec six scénarios : fuite de gaz,
départ de feu, intrusion, effraction, attaque MQTT, brouillage Wi-Fi (coupure puis rejeu du tampon).
Un scénario se lance aussi par l'adresse : `/?demo&scenario=gas` (`fire`, `intrusion`, `tamper`, `cyber`, `jamming`).
Secours le jour de la soutenance si l'API ou le boîtier flanche.

## Connexion à l'API

Jeton opérateur (`OPERATOR_TOKEN` de `infra/.env`), gardé dans `sessionStorage` (effacé à la fermeture de l'onglet).
Formats attendus de chaque route et du WebSocket : `docs/contracts.md`, section « Formats attendus par le dashboard ».
Toutes les vues ne parlent qu'à l'interface `DataSource` (`src/api/source.ts`) : `live.ts` pour l'API, `demo.ts` pour
le simulateur. Le WebSocket se reconnecte seul (1 s, puis jusqu'à 15 s). Le flux vidéo s'ouvre avec un ticket de 60 s
demandé à l'API (`POST /api/v1/video/ticket`), jamais avec le jeton. nginx impose une CSP stricte : aucune ressource
extérieure (police, script, image) n'est chargée.

## Vues

| Vue | Contenu |
| --- | --- |
| Supervision | Sentinel Score (chiffre, niveau, courbe 15 min), scores par domaine, incidents ouverts ; par boîtier : voyant, mesures, courbes température / humidité / gaz avec seuils, commandes |
| Incidents | Filtres (statut, domaine, gravité), explication, facteurs dominants, prévision « critique dans N min », acquitter / résoudre |
| Vision | Flux `/video` annoté, images par seconde, latence, détections récentes |
| Système | Services (temps réel, API, MQTT, base, Brain, vision), charge du PC serveur, santé de chaque boîtier |
| Réglages | Profil de site : seuils, sensibilités de Brain, mode par défaut, boîtiers, vision (`GET/PUT /api/v1/config`) |

## Règles de visualisation

- Un graphique par mesure (jamais deux échelles sur un même graphique), une couleur de série, tableau à la demande.
- Info-bulle au survol et au clavier (flèches), coupure de la courbe quand le boîtier est hors ligne.
- Couleurs d'état (normal, vigilance, alerte, critique) réservées à la gravité, toujours avec icône et libellé.
- Thème clair et sombre (automatique, ou bouton **Thème**), grosses polices pour la salle et Teams.

## Structure

```
src/
  types.ts          types du contrat d'interface
  api/              source.ts (interface), live.ts (API réelle), demo.ts (simulateur)
  state.tsx         état partagé, chargement initial, flux temps réel
  format.ts         libellés français, formats, niveaux de score, voyant du boîtier
  components/       LineChart, Meter, StatusIcon, FactorBars
  views/            Supervision, Incidents, Vision, Systeme, Reglages, Login
```
