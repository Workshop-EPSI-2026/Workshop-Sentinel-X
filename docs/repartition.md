# Répartition de l'équipe — v2

Généré depuis `.github/kanban/tasks.yml` ; le suivi au jour le jour se fait dans le Kanban GitHub.

## Décisions qui structurent la répartition

- **Matériel réel** : ESP32-S3 N16R8, DHT11, module MQ-2, PIR HW-416-B, Raspberry Pi 5 et Raspberry Pi 4 Model B.
- **Option A** : Pi 5 dans le boîtier (point d'accès, Docker, IA). **Pi 4** : repli à chaud et station d'audit.
- **Socle d'abord** : flux TLS de bout en bout, garde locale, Sentinel Brain couches 1 à 3, vision avec zone. Les extensions (TLS mutuel, détection cyber, Réglages, bascule) viennent ensuite.
- **Points de fragilité** : MQTT serveur (Constantin → Lisa), YOLO (Momo → Jeffrick), storyboard (Constantin), pitch (Jeffrick).

## Rôles, binômes et dossiers

| Membre | Compte GitHub | Rôle | Binômes | Dossiers (CODEOWNERS) |
|---|---|---|---|---|
| Constantin | `Datebayo350` | Lead intégration · Backend · Stack Docker sur le Pi · Dashboard | Lisa, Jeffrick | `api/`, `dashboard/`, `infra/` (co), `config/` (co), `.github/`, `docs/` |
| Jeffrick | `tech-200` | Lead IA et data · Sentinel Brain · Vision · BDD · Pitch | Momo | `ai/` (vision, Sentinel Brain), `config/` (co), `tools/`, schéma BDD |
| Momo | `Momo43-ui` | Lead embarqué · Firmware ESP32-S3 · Câblage | Michel, Lisa | `firmware/`, `docs/cablage.md` |
| Lisa | `lisahammani601-del` | Lead cybersécurité · PKI · Hardening · Audit · Dossier | Constantin, Michel | `security/`, `infra/mosquitto/` (co), `docs/securite.md`, `docs/preuves/` |
| Michel | `kokoayimichel-creator` | Raspberry Pi 5 et 4 · Réseau de table · Matériel · Fablab · Vidéo | Momo, Constantin, Lisa | `infra/` (co, Pi 5 et Pi 4), `docs/reseau.md`, `docs/fablab/` |

## Charge par personne

| Membre | Tâches | dont bloquantes | Tâches collectives |
|---|---|---|---|
| Constantin | 18 | 9 | 12 |
| Jeffrick | 12 | 7 | 12 |
| Momo | 8 | 5 | 12 |
| Lisa | 12 | 6 | 12 |
| Michel | 11 | 6 | 12 |

## Tâches collectives

| ID | Tâche | Pilote | Jour | Durée | Bloquant |
|---|---|---|---|---|---|
| g1 | Valider la répartition des rôles | — | Lundi | 10 min | oui |
| g2 | Acter l’Option A (Pi 5) et le repli sur le Pi 4 | — | Lundi | 10 min | oui |
| g4 | Schéma d’architecture et des flux | Constantin | Lundi | 30 min | oui |
| g8 | Validation des schémas par un coach | — | Lundi | 15 min | oui |
| g9 | Synchro de 17h | — | Lundi | 30 min |  |
| p3 | Décision go / no-go : Pi 5 ou bascule sur le Pi 4 | — | Mardi | 15 min | oui |
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
| p1 | Installer et préparer le Raspberry Pi 5 et le Raspberry Pi 4 | Lundi 13h30 – 17h30 | 1 h | Michel | **oui** | SSH par clé sur les deux Pi depuis deux laptops, hello-world passe sur les deux, get_throttled = 0x0 sur le Pi 5. |
| c1 | Stack Docker minimale sur le Raspberry Pi | Lundi 13h30 – 17h30 | 1 h 30 | — | **oui** | mosquitto_pub/sub fonctionne avec identifiants depuis un laptop connecté au Wi-Fi du Pi. |
| c2 | API squelette | Lundi 13h30 – 17h30 | 2 h | — | **oui** | Une donnée simulée publiée sur MQTT arrive en WebSocket. |
| c3 | Passation MQTT serveur à Lisa | Lundi 13h30 – 17h30 | 45 min | — |  | Lisa sait lancer et lire un abonnement MQTT seule. |
| c4 | Mosquitto en TLS (8883 boîtiers, 8884 services) avec ACL | Mardi | 2 h | Lisa | **oui** | mosquitto_sub en 8883 avec CA fonctionne, un client anonyme est refusé. |
| c5 | Persistance et historique | Mardi | 2 h | Jeffrick | **oui** | Les données de la journée sont en BDD et relisibles. |
| c6 | Dashboard v1 | Mardi | 3 h | — | **oui** | Une commande depuis le dashboard fait sonner le buzzer. |
| p2 | Budget de ressources du Pi | Mardi | 45 min | Jeffrick |  | Stack complète plus YOLO sous 3 Go de RAM, pas de bridage thermique après 30 min. |
| li2 | Sécurité de l’API | Mardi | 1 h | Lisa |  | Les deux tests passent. |
| mi4 | Logo, numéro de série et storyboard | Mardi | 1 h 30 | Michel |  | Storyboard et fichiers de gravure dans docs/. |
| g11 | Captures pour la vidéo | Mercredi matin | 30 min | — |  | Clips dans le dossier partagé. |
| je6 | Profil de site et page Réglages | Mercredi matin | 2 h | Jeffrick |  | Une sensibilité modifiée dans la page Réglages change le comportement sans redémarrage. |
| p4 | Répétition de bascule sur le Pi 4 | Mercredi après-midi et soir | 45 min | Michel |  | Bascule réalisée en moins de 10 minutes, sans perte de mesure. |
| li5 | Pentest croisé et rapport d’audit | Jeudi | après-midi | Lisa | **oui** | Rapport intégré au dossier. |
| je4 | Présentation et pitch | Jeudi | 3 h | Jeffrick | **oui** | Workshop2026-M1-G<n>-Pres.pptx prêt, répété une fois. |

## Jeffrick

| ID | Tâche | Créneau | Durée | Avec | Bloquant | Fini quand |
|---|---|---|---|---|---|---|
| g5 | Contrat d’interface | Lundi 11h15 – 12h30 | 30 min | Constantin, Momo | **oui** | docs/contracts.md commité et annoncé au groupe. |
| j1 | Simulateur d’ESP | Lundi 13h30 – 17h30 | 45 min | — | **oui** | Constantin reçoit les données simulées dans l’API. |
| j2 | Mesures YOLO sur le Pi 5 et le Pi 4 | Lundi 13h30 – 17h30 | 1 h 30 | Momo | **oui** | Meilleure configuration retenue pour chaque Pi, tableau commité. |
| j3 | Prototype de Sentinel Brain (4 couches) | Lundi 13h30 – 17h30 | 1 h 30 | — |  | Sur les scénarios simulés, le score monte et eta_min est calculé avant tout seuil brut. |
| c5 | Persistance et historique | Mardi | 2 h | Constantin | **oui** | Les données de la journée sont en BDD et relisibles. |
| p2 | Budget de ressources du Pi | Mardi | 45 min | Constantin |  | Stack complète plus YOLO sous 3 Go de RAM, pas de bridage thermique après 30 min. |
| je1 | Vision v1 : suivi, zone et intégrité de la caméra | Mardi | 3 h | — | **oui** | Une personne entre dans la zone : alerte au dashboard ; caméra masquée : alerte sabotage. |
| je2 | Collecte et provocation d’anomalies réelles | Mardi | 1 h | — |  | Jeu de données réel étiqueté exporté en CSV. |
| je3 | Sentinel Brain en production | Mercredi matin | 2 h | — | **oui** | Sur un scénario provoqué, l’incident arrive expliqué avec une prévision avant le seuil brut. |
| je5 | Détection des attaques cyber dans Sentinel Brain | Mercredi après-midi et soir | 1 h 30 | Lisa |  | Une attaque de test (connexion refusée en boucle, rejeu) produit un incident cyber au dashboard. |
| je6 | Profil de site et page Réglages | Mercredi matin | 2 h | Constantin |  | Une sensibilité modifiée dans la page Réglages change le comportement sans redémarrage. |
| je4 | Présentation et pitch | Jeudi | 3 h | Constantin | **oui** | Workshop2026-M1-G<n>-Pres.pptx prêt, répété une fois. |

## Momo

| ID | Tâche | Créneau | Durée | Avec | Bloquant | Fini quand |
|---|---|---|---|---|---|---|
| g5 | Contrat d’interface | Lundi 11h15 – 12h30 | 30 min | Constantin, Jeffrick | **oui** | docs/contracts.md commité et annoncé au groupe. |
| j2 | Mesures YOLO sur le Pi 5 et le Pi 4 | Lundi 13h30 – 17h30 | 1 h 30 | Jeffrick | **oui** | Meilleure configuration retenue pour chaque Pi, tableau commité. |
| m1 | Câblage ESP32-S3 et test de chaque composant | Lundi 13h30 – 17h30 | 2 h | Michel | **oui** | Chaque capteur donne une valeur cohérente au moniteur série ; mesures relevées dans docs/cablage.md. |
| m2 | ESP32-S3 connecté en Wi-Fi et MQTT en clair | Lundi 13h30 – 17h30 | 1 h | — |  | Constantin voit les vraies valeurs dans mosquitto_sub. |
| mo1 | Firmware v1 : tâches, garde locale et tampon | Mardi | 3 h | — | **oui** | Wi-Fi coupé 5 min : voyant violet, alarme locale fonctionnelle, aucune mesure perdue au retour du réseau. |
| mo2 | Passage du firmware en TLS | Mardi | 2 h | Lisa | **oui** | Télémétrie reçue en 8883, 1883 fermé. |
| mo3 | Intégration dans le boîtier et test longue durée | Mercredi matin | 2 h | Michel |  | Une heure sans perte de connexion. |
| li7 | TLS mutuel : un certificat par boîtier | Mercredi matin | 1 h 30 | Lisa |  | Le boîtier se connecte en TLS mutuel ; un client sans certificat est refusé. |

## Lisa

| ID | Tâche | Créneau | Durée | Avec | Bloquant | Fini quand |
|---|---|---|---|---|---|---|
| g6 | Plan IP et Wi-Fi de table | Lundi 11h15 – 12h30 | 20 min | Michel | **oui** | Tableau dans docs/reseau.md. |
| l1 | CA locale et certificats | Lundi 13h30 – 17h30 | 1 h 30 | — | **oui** | Certificats générés, chaîne testée, NTP local actif. |
| l2 | Matrice de sécurité et base pentest | Lundi 13h30 – 17h30 | 1 h | — |  | docs/securite.md commité, scan de référence sauvegardé. |
| c4 | Mosquitto en TLS (8883 boîtiers, 8884 services) avec ACL | Mardi | 2 h | Constantin | **oui** | mosquitto_sub en 8883 avec CA fonctionne, un client anonyme est refusé. |
| mo2 | Passage du firmware en TLS | Mardi | 2 h | Momo | **oui** | Télémétrie reçue en 8883, 1883 fermé. |
| li1 | Script de hardening | Mardi | 2 h | — |  | Script testé, Nmap après hardening sauvegardé. |
| li2 | Sécurité de l’API | Mardi | 1 h | Constantin |  | Les deux tests passent. |
| li3 | Montage de la vidéo | Mercredi après-midi et soir | 3 h | Michel | **oui** | Workshop2026-M1-G<n>-VidDrop.mp4 validé par le groupe. |
| li4 | Preuves de sécurité | Mercredi après-midi et soir | 1 h 30 | — |  | Captures dans docs/preuves/, modèle de rapport prêt. |
| li7 | TLS mutuel : un certificat par boîtier | Mercredi matin | 1 h 30 | Momo |  | Le boîtier se connecte en TLS mutuel ; un client sans certificat est refusé. |
| je5 | Détection des attaques cyber dans Sentinel Brain | Mercredi après-midi et soir | 1 h 30 | Jeffrick |  | Une attaque de test (connexion refusée en boucle, rejeu) produit un incident cyber au dashboard. |
| li5 | Pentest croisé et rapport d’audit | Jeudi | après-midi | Constantin | **oui** | Rapport intégré au dossier. |

## Michel

| ID | Tâche | Créneau | Durée | Avec | Bloquant | Fini quand |
|---|---|---|---|---|---|---|
| g6 | Plan IP et Wi-Fi de table | Lundi 11h15 – 12h30 | 20 min | Lisa | **oui** | Tableau dans docs/reseau.md. |
| p1 | Installer et préparer le Raspberry Pi 5 et le Raspberry Pi 4 | Lundi 13h30 – 17h30 | 1 h | Constantin | **oui** | SSH par clé sur les deux Pi depuis deux laptops, hello-world passe sur les deux, get_throttled = 0x0 sur le Pi 5. |
| m1 | Câblage ESP32-S3 et test de chaque composant | Lundi 13h30 – 17h30 | 2 h | Momo | **oui** | Chaque capteur donne une valeur cohérente au moniteur série ; mesures relevées dans docs/cablage.md. |
| mi1 | Point d’accès Wi-Fi de table | Lundi 13h30 – 17h30 | 1 h | — | **oui** | L’ESP obtient son IP réservée et pingue le serveur. |
| mi2 | Mesures et esquisse du boîtier | Lundi 13h30 – 17h30 | 1 h | — |  | Esquisse cotée dans Fusion 360, créneau réservé. |
| mi3 | Boîtier finalisé et impression lancée | Mardi | 3 h | — | **oui** | Impression lancée mardi midi au plus tard. |
| mi4 | Logo, numéro de série et storyboard | Mardi | 1 h 30 | Constantin |  | Storyboard et fichiers de gravure dans docs/. |
| mo3 | Intégration dans le boîtier et test longue durée | Mercredi matin | 2 h | Momo |  | Une heure sans perte de connexion. |
| li3 | Montage de la vidéo | Mercredi après-midi et soir | 3 h | Lisa | **oui** | Workshop2026-M1-G<n>-VidDrop.mp4 validé par le groupe. |
| mi5 | Gravure laser | Mercredi après-midi et soir | 1 h | — |  | Façade gravée et montée. |
| p4 | Répétition de bascule sur le Pi 4 | Mercredi après-midi et soir | 45 min | Constantin |  | Bascule réalisée en moins de 10 minutes, sans perte de mesure. |

## Règles

- Une issue n'est fermée que si sa définition de « fini » est atteinte.
- Les tâches `bloquant` passent avant tout le reste ; les extensions seulement si le socle est stable.
- **Mardi 18 h** : si une vraie mesure de l'ESP32-S3 n'apparaît pas au dashboard en TLS, on arrête les fonctionnalités et tout le monde aide à l'intégration.
- Chacun commite lui-même, régulièrement.
