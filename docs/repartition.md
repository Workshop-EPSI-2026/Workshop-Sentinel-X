# Répartition de l'équipe

Source : plan d'équipe validé lundi (matrice de compétences). Ce fichier est généré à partir de `.github/kanban/tasks.yml` ; le suivi au jour le jour se fait dans le Kanban GitHub.

## Décisions qui structurent la répartition

- **Option A retenue** : Raspberry Pi 5 dans le boîtier, webcam USB sur le Pi, ESP8266 connecté au Wi-Fi du Pi (point d'accès).
- **Plan de repli** : la même stack Docker et le même script vision tournent sur un laptop Linux. Décision go / no-go mardi 18 h (tâche p3).
- **Trous de la matrice** (embarqué, réseau, cyber, CAO, vidéo) : couverts par des binômes et une demande d'aide aux coachs dès lundi.
- **Points de fragilité** : MQTT serveur (Constantin → Lisa), YOLO (Momo → Jeffrick), storyboard (Constantin), pitch (Jeffrick). Passation obligatoire.

## Rôles, binômes et dossiers du dépôt

| Membre | Rôle | Binômes | Dossiers dont il est propriétaire (CODEOWNERS) |
|---|---|---|---|
| Constantin | Lead intégration · Backend · Stack Docker sur le Pi · Dashboard | Lisa, Jeffrick | `api/`, `dashboard/`, `infra/` (co), `.github/`, `docs/` (architecture) |
| Jeffrick | Lead IA et data · Anomalies · Vision · BDD · Pitch | Momo | `ai/`, `tools/simulator.py`, schéma BDD (`infra/postgres/init/`) |
| Momo | Lead embarqué · Firmware ESP8266 · Câblage | Michel, Lisa | `firmware/`, `docs/cablage.md` |
| Lisa | Lead cybersécurité · PKI · Hardening · Audit · Dossier | Constantin, Michel | `security/`, `infra/mosquitto/` (co), `docs/securite.md`, `docs/preuves/` |
| Michel | Raspberry Pi et réseau de table · Matériel · Fablab · Vidéo | Momo, Constantin, Lisa | `infra/` (co, Pi et réseau), `docs/reseau.md`, `docs/fablab/` |

## Charge par personne

| Membre | Tâches | dont bloquantes | dont en solo | Tâches collectives (« Tous ») |
|---|---|---|---|---|
| Constantin | 16 | 9 | 7 | 12 |
| Jeffrick | 10 | 7 | 5 | 12 |
| Momo | 7 | 5 | 2 | 12 |
| Lisa | 10 | 6 | 4 | 12 |
| Michel | 10 | 6 | 4 | 12 |

## Tâches collectives (toute l'équipe)

| ID | Tâche | Pilote | Jour | Durée | Bloquant |
|---|---|---|---|---|---|
| g1 | Valider la répartition des rôles | — | Lundi | 10 min | oui |
| g2 | Acter l’Option A et organiser le plan de repli | — | Lundi | 10 min | oui |
| g4 | Schéma d’architecture et des flux | Constantin | Lundi | 30 min | oui |
| g8 | Validation des schémas par un coach | — | Lundi | 15 min | oui |
| g9 | Synchro de 17h | — | Lundi | 30 min |  |
| p3 | Décision go / no-go sur le Pi | — | Mardi | 15 min | oui |
| g10 | Point de contrôle de mardi soir | — | Mardi | 30 min | oui |
| c7 | Intégration globale | Constantin | Mercredi | 3 h | oui |
| g12 | Tournage fond vert | — | Mercredi | 2 h | oui |
| g13 | Gel du code et répétition de démo | — | Jeudi | matin | oui |
| li6 | Dossier PDF et rendus | Lisa | Jeudi | soir | oui |
| v1 | Dépôt du prototype et soutenance | — | Vendredi | matin | oui |

## Constantin

| ID | Tâche | Créneau | Durée | Avec | Bloquant | Fini quand |
|---|---|---|---|---|---|---|
| g3 | Questions aux coachs | Lundi 11h15 – 12h30 | 10 min | — |  | Réponses notées dans le dépôt (docs/coachs.md). |
| g5 | Contrat d’interface | Lundi 11h15 – 12h30 | 30 min | Momo, Jeffrick | **oui** | docs/contracts.md commité et annoncé au groupe. |
| g7 | Dépôt Git, Kanban et conventions | Lundi 11h15 – 12h30 | 15 min | — |  | Tout le monde a cloné et fait un premier commit. |
| p1 | Installer et préparer le Raspberry Pi 5 | Lundi 13h30 – 17h30 | 1 h | Michel | **oui** | SSH par clé fonctionne depuis deux laptops, docker run hello-world passe, get_throttled = 0x0. |
| c1 | Stack Docker minimale sur le Raspberry Pi | Lundi 13h30 – 17h30 | 1 h 30 | — | **oui** | mosquitto_pub/sub fonctionne avec identifiants depuis un laptop connecté au Wi-Fi du Pi. |
| c2 | API squelette | Lundi 13h30 – 17h30 | 2 h | — | **oui** | Une donnée simulée publiée sur MQTT arrive en WebSocket. |
| c3 | Passation MQTT serveur à Lisa | Lundi 13h30 – 17h30 | 45 min | — |  | Lisa sait lancer et lire un abonnement MQTT seule. |
| c4 | Mosquitto en TLS 8883 avec ACL | Mardi | 2 h | Lisa | **oui** | mosquitto_sub en 8883 avec CA fonctionne, un client anonyme est refusé. |
| c5 | Persistance et historique | Mardi | 2 h | Jeffrick | **oui** | Les données de la journée sont en BDD et relisibles. |
| c6 | Dashboard v1 | Mardi | 3 h | — | **oui** | Une commande depuis le dashboard fait sonner le buzzer. |
| p2 | Budget de ressources du Pi | Mardi | 45 min | Jeffrick |  | Stack complète plus YOLO sous 3 Go de RAM, pas de bridage thermique après 30 min. |
| li2 | Sécurité de l’API | Mardi | 1 h | Lisa |  | Les deux tests passent. |
| mi4 | Logo, numéro de série et storyboard | Mardi | 1 h 30 | Michel |  | Storyboard et fichiers de gravure dans docs/. |
| g11 | Captures pour la vidéo | Mercredi matin | 30 min | — |  | Clips dans le dossier partagé. |
| li5 | Pentest croisé et rapport d’audit | Jeudi | après-midi | Lisa | **oui** | Rapport intégré au dossier. |
| je4 | Présentation et pitch | Jeudi | 3 h | Jeffrick | **oui** | Workshop2026-M1-G<n>-Pres.pptx prêt, répété une fois. |

## Jeffrick

| ID | Tâche | Créneau | Durée | Avec | Bloquant | Fini quand |
|---|---|---|---|---|---|---|
| g5 | Contrat d’interface | Lundi 11h15 – 12h30 | 30 min | Constantin, Momo | **oui** | docs/contracts.md commité et annoncé au groupe. |
| j1 | Simulateur d’ESP | Lundi 13h30 – 17h30 | 45 min | — | **oui** | Constantin reçoit les données simulées dans l’API. |
| j2 | Passation YOLO et mesure de latence sur le Pi | Lundi 13h30 – 17h30 | 1 h 30 | Momo | **oui** | Meilleure latence mesurée sur le Pi et notée, configuration retenue. |
| j3 | Prototype du modèle d’anomalies | Lundi 13h30 – 17h30 | 1 h 30 | — |  | Le score monte nettement sur le scénario simulé avant tout seuil brut. |
| c5 | Persistance et historique | Mardi | 2 h | Constantin | **oui** | Les données de la journée sont en BDD et relisibles. |
| p2 | Budget de ressources du Pi | Mardi | 45 min | Constantin |  | Stack complète plus YOLO sous 3 Go de RAM, pas de bridage thermique après 30 min. |
| je1 | Script vision v1 | Mardi | 3 h | — | **oui** | Une personne entre dans la zone : alerte dans le dashboard, flux visible. |
| je2 | Collecte et provocation d’anomalies réelles | Mardi | 1 h | — |  | Jeu de données réel étiqueté exporté en CSV. |
| je3 | Service d’anomalies en production | Mercredi matin | 2 h | — | **oui** | Le score monte avant l’alerte brute sur un scénario provoqué. |
| je4 | Présentation et pitch | Jeudi | 3 h | Constantin | **oui** | Workshop2026-M1-G<n>-Pres.pptx prêt, répété une fois. |

## Momo

| ID | Tâche | Créneau | Durée | Avec | Bloquant | Fini quand |
|---|---|---|---|---|---|---|
| g5 | Contrat d’interface | Lundi 11h15 – 12h30 | 30 min | Constantin, Jeffrick | **oui** | docs/contracts.md commité et annoncé au groupe. |
| j2 | Passation YOLO et mesure de latence sur le Pi | Lundi 13h30 – 17h30 | 1 h 30 | Jeffrick | **oui** | Meilleure latence mesurée sur le Pi et notée, configuration retenue. |
| m1 | Câblage et test de chaque composant | Lundi 13h30 – 17h30 | 2 h | Michel | **oui** | Chaque capteur affiche une valeur cohérente sur le moniteur série et sur l’OLED. |
| m2 | ESP connecté en Wi-Fi et MQTT en clair | Lundi 13h30 – 17h30 | 1 h | — |  | Constantin voit les vraies valeurs dans mosquitto_sub. |
| mo1 | Firmware v1 complet en clair | Mardi | 3 h | — | **oui** | Débrancher puis rebrancher le Wi-Fi : l’ESP se reconnecte seul. |
| mo2 | Passage du firmware en TLS | Mardi | 2 h | Lisa | **oui** | Télémétrie reçue en 8883, 1883 fermé. |
| mo3 | Intégration dans le boîtier et test longue durée | Mercredi matin | 2 h | Michel |  | Une heure sans perte de connexion. |

## Lisa

| ID | Tâche | Créneau | Durée | Avec | Bloquant | Fini quand |
|---|---|---|---|---|---|---|
| g6 | Plan IP et Wi-Fi de table | Lundi 11h15 – 12h30 | 20 min | Michel | **oui** | Tableau dans docs/reseau.md. |
| l1 | CA locale et certificats | Lundi 13h30 – 17h30 | 1 h 30 | — | **oui** | Certificats générés, chaîne testée, NTP local actif. |
| l2 | Matrice de sécurité et base pentest | Lundi 13h30 – 17h30 | 1 h | — |  | docs/securite.md commité, scan de référence sauvegardé. |
| c4 | Mosquitto en TLS 8883 avec ACL | Mardi | 2 h | Constantin | **oui** | mosquitto_sub en 8883 avec CA fonctionne, un client anonyme est refusé. |
| mo2 | Passage du firmware en TLS | Mardi | 2 h | Momo | **oui** | Télémétrie reçue en 8883, 1883 fermé. |
| li1 | Script de hardening | Mardi | 2 h | — |  | Script testé, Nmap après hardening sauvegardé. |
| li2 | Sécurité de l’API | Mardi | 1 h | Constantin |  | Les deux tests passent. |
| li3 | Montage de la vidéo | Mercredi après-midi et soir | 3 h | Michel | **oui** | Workshop2026-M1-G<n>-VidDrop.mp4 validé par le groupe. |
| li4 | Preuves de sécurité | Mercredi après-midi et soir | 1 h 30 | — |  | Captures dans docs/preuves/, modèle de rapport prêt. |
| li5 | Pentest croisé et rapport d’audit | Jeudi | après-midi | Constantin | **oui** | Rapport intégré au dossier. |

## Michel

| ID | Tâche | Créneau | Durée | Avec | Bloquant | Fini quand |
|---|---|---|---|---|---|---|
| g6 | Plan IP et Wi-Fi de table | Lundi 11h15 – 12h30 | 20 min | Lisa | **oui** | Tableau dans docs/reseau.md. |
| p1 | Installer et préparer le Raspberry Pi 5 | Lundi 13h30 – 17h30 | 1 h | Constantin | **oui** | SSH par clé fonctionne depuis deux laptops, docker run hello-world passe, get_throttled = 0x0. |
| m1 | Câblage et test de chaque composant | Lundi 13h30 – 17h30 | 2 h | Momo | **oui** | Chaque capteur affiche une valeur cohérente sur le moniteur série et sur l’OLED. |
| mi1 | Point d’accès Wi-Fi de table | Lundi 13h30 – 17h30 | 1 h | — | **oui** | L’ESP obtient son IP réservée et pingue le serveur. |
| mi2 | Mesures et esquisse du boîtier | Lundi 13h30 – 17h30 | 1 h | — |  | Esquisse cotée dans Fusion 360, créneau réservé. |
| mi3 | Boîtier finalisé et impression lancée | Mardi | 3 h | — | **oui** | Impression lancée mardi midi au plus tard. |
| mi4 | Logo, numéro de série et storyboard | Mardi | 1 h 30 | Constantin |  | Storyboard et fichiers de gravure dans docs/. |
| mo3 | Intégration dans le boîtier et test longue durée | Mercredi matin | 2 h | Momo |  | Une heure sans perte de connexion. |
| li3 | Montage de la vidéo | Mercredi après-midi et soir | 3 h | Lisa | **oui** | Workshop2026-M1-G<n>-VidDrop.mp4 validé par le groupe. |
| mi5 | Gravure laser | Mercredi après-midi et soir | 1 h | — |  | Façade gravée et montée. |

## Règles du plan

- Une tâche n'est fermée que si sa définition de « fini » est atteinte (issue fermée = case cochée).
- Les tâches `bloquant` passent avant tout le reste.
- **Mardi soir** : si le flux ESP8266 → Mosquitto → API → dashboard ne tourne pas avec une vraie valeur, on arrête les fonctionnalités et tout le monde aide à l'intégration.
- Chacun commite lui-même, régulièrement (la note est aussi individuelle).
