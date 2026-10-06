# Sentinel-X — Architecture v2

> Version alignée sur le matériel réellement disponible : ESP32-S3 N16R8, DHT11, module MQ-2,
> PIR HW-416-B (BISS0001) ; partie serveur hébergée sur un PC Windows 11 (pas de Raspberry Pi).
> Les schémas illustrés se trouvent dans le document d'architecture partagé de l'équipe.

## 1. Synthèse

Sentinel-X v2 est un système de détection **multicouche et autonome**. Le boîtier ne se contente pas
de transmettre des mesures : il raisonne déjà localement, garde ses données quand le réseau tombe et
déclenche une alarme réflexe même si le serveur est éteint. Sur le PC serveur, un moteur de
détection (« Sentinel Brain ») fusionne trois domaines de menace — environnement, intrusion physique et
cyberattaque — en un score unique et explique chaque alerte en langage clair.

| Décision | Choix |
| --- | --- |
| Boîtier | ESP32-S3 N16R8 (2 cœurs, 8 Mo de PSRAM, crypto matérielle, capteurs tactiles intégrés) |
| Serveur | PC Windows 11 : point d'accès Wi-Fi mobile, Docker Desktop (WSL2), vision hors Docker (webcam USB) |
| Repli | Redémarrage complet du PC répété et chronométré, simulateur d'ESP en secours ; audit depuis un laptop de l'équipe |
| Communication | MQTT : 1883 authentifié lundi, TLS 8883 mardi, TLS mutuel (certificat par boîtier) en cible |
| Détection | 4 couches : qualité des données, détection par capteur (EWMA, MAD, CUSUM), multivariée (Isolation Forest), prévision (Holt) ; puis fusion et règles de corrélation |
| Vision | YOLOv8n en NCNN, 320 px, suivi des personnes, zone interdite, temps de présence, détection de caméra masquée |
| Personnalisation | Profil de site (`config/site.example.yml`) modifiable à chaud depuis le dashboard, appliqué au boîtier et au serveur |
| Données | PostgreSQL 16 ; pas d'InfluxDB ni de Grafana (un seul moteur à maintenir) |

Principes : **autonomie à trois niveaux**, **sécurité dès mardi**, **aucune dépendance à Internet le jour de la démo**,
**chaque alerte expliquée**, **un seul fichier de configuration par site**.

## 2. Matériel réel et exploitation maximale

| Composant | Capacités exploitées | Limites | Parade |
| --- | --- | --- | --- |
| ESP32-S3 N16R8 | 2 cœurs (FreeRTOS), 8 Mo de PSRAM pour un tampon de plusieurs heures, crypto matérielle (TLS mutuel), entrées tactiles capacitives, capteur de température interne, LED RGB intégrée | Broches réservées : 0, 3, 45, 46 (démarrage), 19-20 (USB), 35-37 (PSRAM), 43-44 (série) ; ADC utilisable avec le Wi-Fi : GPIO 1 à 10 | Brochage figé dans `firmware/include/pins.h` |
| DHT11 | Température et humidité, point de rosée calculé | ±2 °C, pas de 1 °C, 0-50 °C, 1 lecture/s maximum | Lissage avant calcul de pente, fenêtres de 60 s, le gaz porte la détection fine ; sèche-cheveux à distance en démo |
| MQ-2 (module) | Sortie analogique en millivolts calibrés et ratio par rapport à la ligne de base apprise ; sortie DO en seuil matériel par interruption | Chauffe, préchauffage nécessaire, sortie jusqu'à 5 V, pas de mesure en ppm sans gaz étalon | Ponts diviseurs, ligne de base apprise au démarrage, on parle de « ratio » et non de ppm |
| PIR HW-416-B | Détection de mouvement jusqu'à environ 7 m, comptage d'événements par minute | Temps mort, sensible à la chaleur | Cavalier en mode H (redéclenchable), sensibilité au maximum, délai au minimum ; fusion avec la vision |
| PC serveur Windows 11 | Serveur complet, point d'accès Wi-Fi, YOLO sur le processeur du PC | Veille et mises à jour Windows, webcam inaccessible depuis Docker Desktop, point d'accès à réactiver après redémarrage | Veille désactivée, mises à jour suspendues, vision lancée hors Docker, redémarrage répété |
| Webcam USB, buzzer, LEDs, LCD 1602 | Vision ; alarme sonore et visuelle ; affichage de l'état sur le boîtier | LCD sans module I2C : 6 broches, contraste à régler | Mode 4 bits, RW à la masse, résistance fixe de contraste sur V0 |

Idée clé : **une feuille de cuivre collée à l'intérieur du couvercle, reliée à une entrée tactile de l'ESP32-S3,
devient un détecteur d'effraction gratuit**. Toute manipulation du boîtier est détectée sans composant supplémentaire.

## 3. Architecture globale

Une mesure suit toujours le même chemin : l'ESP32-S3 la publie en MQTT chiffré au broker du PC serveur, l'API la stocke et
la pousse au dashboard, Sentinel Brain la score. La vision, lancée sur le PC hors Docker et branchée sur la webcam,
envoie ses détections à l'API par nginx.
L'opérateur ne voit que nginx, en HTTPS.

### Autonomie à trois niveaux

| Niveau | Ce qui fonctionne | Exemple |
| --- | --- | --- |
| 1 · Boîtier seul | Mesures, garde locale, alarme réflexe (LED et buzzer), tampon de plusieurs heures en PSRAM | Le Wi-Fi est brouillé : l'ESP sonne quand même et renvoie tout l'historique au retour du réseau |
| 2 · Boîtier + PC serveur | Tout le système, sans Internet | Configuration de la démo |
| 3 · Intégration | API documentée, webhook sortant, export CSV, topics MQTT documentés | Remontée vers une supervision AetherCorp |

### Liens et ports

| Lien | Protocole | Port | Chiffré |
| --- | --- | --- | --- |
| ESP32-S3 vers broker | MQTT (télémétrie, événements, santé), retour des commandes et de la configuration | 8883 (1883 lundi) | Oui, TLS puis TLS mutuel |
| Services vers broker | MQTT dans Docker | 8884 interne | Oui |
| Brain vers API | HTTP `POST /api/v1/alerts` dans Docker | 8000 interne | Non exposé |
| Vision vers API | HTTPS par nginx (`https://localhost`), depuis le PC | 443 | Oui |
| nginx vers vision | HTTP vers `host.docker.internal` (`/video`) | 8001 sur 127.0.0.1 | Local au PC |
| API vers base | PostgreSQL, réseau interne | 5432 interne | Non exposé |
| Navigateur vers nginx | HTTPS, WSS (`/ws`), MJPEG (`/video`) | 443 | Oui |
| Administration | Directement sur le PC serveur, pas de SSH | — | — |

## 4. Bloc IoT : Edge Node ESP32-S3

### Brochage

| Composant | Broche | Alimentation | Remarque |
| --- | --- | --- | --- |
| DHT11 DATA | GPIO 4 | 3,3 V | Résistance de tirage sur le module |
| PIR OUT | GPIO 5 | 5 V | Sortie 3,3 V, interruption sur front montant |
| MQ-2 AO | GPIO 1 (ADC1) | 5 V | Pont 10 kΩ / 10 kΩ (max 2,5 V), moyenne de 16 lectures en mV |
| MQ-2 DO | GPIO 6 | — | Pont 10 kΩ / 15 kΩ (≈ 3 V), seuil matériel par interruption |
| Effraction (tactile) | GPIO 7 (T7) | — | Feuille de cuivre dans le couvercle, seuil auto-calibré |
| LCD 1602 RS / E | GPIO 8 / 9 | 5 V | Mode 4 bits, RW à la masse |
| LCD 1602 D4 à D7 | GPIO 13 à 16 | — | Contraste par résistance fixe V0 → GND (≈ 1 kΩ) |
| Buzzer | GPIO 10 | — | Alarme sonore locale |
| LED verte / rouge | GPIO 11 / 12 | — | Résistance série |
| LED RGB intégrée | GPIO 48 | — | Voyant d'état (38 sur certaines cartes) |

Couleurs du voyant : **vert** surveillance, **bleu** apprentissage, **orange** suspicion, **rouge** alarme,
**violet** hors ligne (tampon actif), **blanc** maintenance.

### Firmware (FreeRTOS, deux cœurs)

| Tâche | Cœur | Rôle |
| --- | --- | --- |
| Capteurs | 1 | DHT11 toutes les 2 s, MQ-2 en mV calibrés, interruptions PIR, DO et effraction, température interne |
| Garde locale | 1 | Ligne de base EWMA par capteur, écart robuste, pente ; alarme réflexe sans le serveur ; échantillonnage accéléré à 500 ms pendant 60 s en cas de suspicion |
| Réseau | 0 | Wi-Fi et MQTT TLS, QoS 1 pour les événements, tampon circulaire en PSRAM rejoué avec les horodatages d'origine, message de dernière volonté |
| Santé | 0 | Toutes les 30 s : mémoire, RSSI, température de la puce, raison du dernier redémarrage, taille du tampon, déconnexions Wi-Fi et erreurs TLS |

Modes : **APPRENTISSAGE** (10 min après démarrage ou sur commande), **SURVEILLANCE**, **MAINTENANCE** (alarmes coupées).
La configuration reçue sur `sentinel/<id>/config` est appliquée immédiatement et enregistrée en mémoire non volatile (NVS).

### Mise en place

1. PlatformIO, carte `esp32-s3-devkitc-1`, PSRAM activée ; téléverser par le port USB-C marqué **COM**.
2. Câbler et tester chaque capteur seul, valeurs sur le moniteur série.
3. Ponts diviseurs du MQ-2, préchauffage dès le branchement, relever la valeur au repos.
4. Feuille de cuivre et seuil tactile ; tester une main posée sur le couvercle.
5. Wi-Fi du PC (point d'accès mobile, 2,4 GHz), broker 192.168.137.1, MQTT en clair sur 1883 avec identifiants.
6. Tâches FreeRTOS, garde locale, voyant RGB, tampon PSRAM, santé.
7. TLS sur 8883 avec la CA embarquée (`WiFiClientSecure::setCACert`), heure par le NTP du PC (service Temps Windows).
8. TLS mutuel : certificat client du boîtier fourni par Lisa.

**Fini quand** : Wi-Fi coupé 5 minutes, le voyant passe en violet, l'alarme locale fonctionne, et au retour du réseau
toutes les mesures arrivent sans trou, en TLS.

## 5. Bloc Réseau

| Équipement | Adresse | Attribution |
| --- | --- | --- |
| PC serveur (point d'accès, Docker, vision, `sentinel-pc`) | 192.168.137.1 | Fixe (point d'accès mobile Windows) |
| ESP32-S3 `esp-01` | DHCP | Lue dans la page Point d'accès mobile |
| Postes de l'équipe | DHCP | 8 appareils au maximum sur le point d'accès |

Ports ouverts sur le PC serveur : 443 (HTTPS, WSS), 8883 (MQTTS), 123/udp (NTP). Tout le reste est refusé par le pare-feu Windows.
Wi-Fi 2,4 GHz, WPA2, phrase de passe de 20 caractères minimum, hors dépôt.
Préparation du PC (veille, NTP, pare-feu) et procédure de redémarrage : `docs/reseau.md`.

## 6. Bloc Infrastructure : PC serveur et Docker

| Conteneur | Rôle | Réseaux | Port publié | Mémoire max | Profil |
| --- | --- | --- | --- | --- | --- |
| `mosquitto` | Bus MQTT, TLS, ACL ; 8883 boîtiers, 8884 services | app | 8883 | 64 Mo | socle |
| `postgres` | Historique, alertes, configuration | data (interne) | aucun | 384 Mo | socle |
| `api` | REST, WebSocket, ingestion, configuration | app, data | aucun | 256 Mo | app |
| `nginx` | HTTPS, WSS, dashboard, limitation de débit | app | 443 | 64 Mo | app |
| `vision` | YOLO, suivi, zone, caméra masquée, `/video` ; **hors Docker sur le PC** (`ai/vision/run-windows.ps1`) | — | aucun (127.0.0.1:8001) | — | `vision` (hôte Linux uniquement) |
| `anomaly` (Sentinel Brain) | Détection multicouche, fusion, score | app | aucun | 512 Mo | ai |

Docker Desktop sous Windows n'a pas accès à la webcam : la vision tourne donc directement sur le PC, parle à l'API
par nginx et lui fournit `/video`. Le conteneur `vision` reste disponible pour un hôte Linux.

Tous les conteneurs : redémarrage automatique, contrôle de santé, sans root, `no-new-privileges`, capacités retirées,
journaux limités. Le journal de Mosquitto est partagé en lecture seule avec Sentinel Brain pour détecter les
tentatives d'accès refusées.

### Mise en place

1. PC serveur préparé : Docker Desktop (WSL2), Git, Python 3.12, veille désactivée, NTP, pare-feu (`docs/reseau.md`).
2. `infra/.env` depuis `.env.example`, comptes Mosquitto (`infra/mosquitto/README.md`).
3. Socle lundi (Mosquitto + PostgreSQL, 1883), puis TLS mardi (`MOSQUITTO_CONF=mosquitto.tls.conf`), puis profils `app` et `ai`,
   et la vision lancée à part.
4. Budget mesuré avec toute la stack et la vision (`docker stats`, Gestionnaire des tâches) : stable après 30 minutes.
5. Répétition du redémarrage du PC serveur : moins de 10 minutes chronométrées.

## 7. Bloc Backend et Dashboard

| Route | Méthode | Rôle |
| --- | --- | --- |
| `/api/v1/alerts` | POST | Ingestion d'une alerte (vision, Brain), clé d'API |
| `/api/v1/alerts` | GET | Incidents filtrés par statut, domaine, gravité |
| `/api/v1/alerts/{id}` | PATCH | Acquitter ou clore un incident |
| `/api/v1/telemetry?from=&device=` | GET | Historique paginé |
| `/api/v1/commands` | POST | Commande vers un boîtier (alarme, mode, recalibrage, redémarrage) |
| `/api/v1/config` | GET / PUT | Profil de site ; publié en message conservé aux boîtiers et à Brain |
| `/api/v1/score` | GET | Scores courants par domaine |
| `/api/v1/health` | GET | Santé du serveur et des boîtiers |
| `/ws` | WebSocket | Télémétrie, scores, incidents en temps réel |

Cycle de vie d'un incident : **ouvert → acquitté → résolu**, avec regroupement des répétitions, délai minimal entre deux
notifications et escalade de gravité si la situation persiste. Chaque action d'opérateur est tracée (`audit_log`).

Vues du dashboard : **Supervision** (jauge Sentinel Score, courbes, voyant du boîtier), **Incidents** (explication de
chaque alerte, acquittement), **Vision** (flux annoté, zone, FPS), **Système** (santé de chaque brique, serveur et boîtiers),
**Réglages** (profil de site, modes, sensibilités, zone de la caméra).

### Mise en place

1. Squelette : `/health`, `POST /alerts` validé ; client MQTT ; WebSocket ; test avec le simulateur.
2. Base : tables `telemetry`, `events`, `health`, `alerts`, `commands`, `config_versions`, `audit_log`.
3. Dashboard v1 : supervision et incidents ; commandes.
4. Configuration : `GET/PUT /config`, page Réglages, publication MQTT conservée.
5. Sécurité avec Lisa : clé d'API, limitation de débit, authentification de l'interface.

## 8. Bloc IA : Sentinel Brain et vision

### Les quatre couches de détection

| Couche | Méthode | Ce qu'elle attrape |
| --- | --- | --- |
| 1 · Qualité des données | Plausibilité, capteur figé, trous de séquence, rejeu | Capteur défaillant, message injecté ou rejoué |
| 2 · Par capteur | Ligne de base EWMA, écart robuste (médiane, MAD), CUSUM | Pics brutaux et dérives lentes persistantes |
| 3 · Multivariée | Isolation Forest sur fenêtres de 60 s | Combinaisons inhabituelles même si chaque valeur paraît normale |
| 4 · Prévision | Lissage exponentiel double (Holt) | « Niveau critique atteint dans 4 min » |

Le CUSUM est la méthode de référence de la maîtrise statistique des procédés industriels : il cumule les petits écarts
et détecte une dérive bien avant qu'un seuil soit franchi.

### Fusion et incidents

Trois scores de 0 à 100 — **environnement**, **physique**, **cyber** — et un **Sentinel Score** global (le maximum
pondéré). Des règles de corrélation transforment les signaux en incidents nommés :

| Incident | Condition |
| --- | --- |
| Intrusion confirmée | PIR et personne dans la zone à moins de 5 s d'écart |
| Intrusion présumée | PIR seul la nuit ou vision seule ; gravité moindre |
| Rôdeur | Personne présente dans la zone plus de N secondes |
| Sabotage | Effraction tactile, caméra masquée, ou boîtier hors ligne juste après une détection |
| Risque incendie | Hausse de température et du ratio gaz en même temps |
| Fuite de gaz | Alarme CUSUM sur le gaz, température stable |
| Brouillage Wi-Fi présumé | Chute de RSSI suivie de déconnexions répétées |
| Attaque cyber | Rafale d'accès MQTT refusés, client inconnu, rejeu, rafale de 401 ou 429 sur l'API |
| Capteur défaillant | Valeur figée ou impossible ; incident de maintenance, pas de sécurité |

Chaque incident porte son **explication** : les facteurs qui ont le plus pesé, en phrase lisible
(« gaz +38 % au-dessus de la ligne de base, pente +2 %/min, température stable »).

### Apprentissage et adaptation

- **Phase d'apprentissage** de 10 minutes au démarrage : lignes de base et premier modèle.
- **Réentraînement périodique** sur les fenêtres récentes sans incident : le modèle suit les variations normales
  (jour, nuit, chauffage) sans apprendre les attaques.
- **Sensibilités par domaine** réglables dans le profil de site.

### Vision

YOLOv8n exporté en NCNN, image de 320 px, classe personne, suivi (`model.track`) pour compter des personnes distinctes et
mesurer leur temps de présence, zone interdite en polygone. Deux contrôles d'intégrité : **caméra masquée** (image quasi
uniforme) et **faible luminosité** (le poids de la vision baisse, celui du PIR monte). Flux MJPEG annoté sur `/video`.

### Mise en place

1. Simulateur au format v2 avec scénarios (dérive lente, fuite, incendie, intrusion, rejeu).
2. Mesures YOLO sur le PC serveur : PyTorch, NCNN (OpenVINO si besoin), 320 px ; tableau des résultats.
3. Prototype des 4 couches en notebook sur données simulées.
4. Vision v1 : suivi, zone, temps de présence, caméra masquée, `/video`.
5. Données réelles : plusieurs heures de régime normal, scénarios provoqués et horodatés.
6. Brain en production : fusion, règles, explications, réentraînement, score en direct.

**Indicateurs à présenter** : délai d'anticipation (minutes gagnées avant le seuil), taux de faux positifs sur une heure
de régime normal, latence de bout en bout, FPS.

## 9. Bloc Cybersécurité

| Surface | Contre-mesure | Preuve |
| --- | --- | --- |
| Wi-Fi | WPA2-AES, phrase longue, réseau isolé | Configuration |
| MQTT | TLS, puis TLS mutuel : un certificat par boîtier, identité = nom d'utilisateur ; ACL par topic ; 1883 fermé | Wireshark clair contre chiffré ; client sans certificat refusé |
| API | HTTPS, clé d'API, validation stricte, limitation de débit, authentification de l'interface | Payload invalide rejeté, appel sans clé refusé |
| Hôte | Pare-feu Windows refus par défaut (443, 8883, 123/udp), réseau du point d'accès en profil Public, pas de SSH, session protégée | Nmap avant et après |
| Docker | Non root, `no-new-privileges`, base interne, 2 ports publiés | `docker compose config`, Nmap |
| Boîtier | Secrets hors dépôt, compte à droits minimaux, effraction détectée | ACL, démo d'ouverture |
| Détection | Accès refusés, rejeu, brouillage et rafales d'API transformés en incidents cyber | Incident visible pendant le pentest |
| Dépôt | `.gitignore`, gitleaks en CI | Rapport gitleaks |

Le démarrage sécurisé et le chiffrement de la flash de l'ESP32-S3 sont **volontairement non activés** : ils grillent des
fusibles irréversibles. Ils sont présentés comme étape d'industrialisation.

### Mise en place

1. CA locale, certificat serveur (SAN : 192.168.137.1, 127.0.0.1, `sentinel-pc`, `localhost`, `mosquitto`), NTP du PC.
2. TLS sur Mosquitto, ACL ; fermeture de 1883.
3. Certificat client par boîtier, puis `MOSQUITTO_CONF=mosquitto.mtls.conf`.
4. Durcissement de l'hôte, puis Nmap ; preuves dans `docs/preuves/`.
5. Avec Jeffrick : signaux cyber vers Sentinel Brain.
6. Pentest croisé, depuis un laptop de l'équipe comme station d'audit.

## 10. Personnalisation et intégration

Un site = un fichier de profil (`config/site.example.yml`) : capteurs actifs, seuils d'avertissement et critiques,
sensibilité par domaine, zone de la caméra, plages horaires de surveillance, fréquence d'envoi, alarme locale.
Le profil se modifie depuis la page Réglages ; l'API le versionne, le publie en message conservé sur MQTT, et le boîtier
comme Brain l'appliquent sans redémarrage. Ajouter un boîtier = un certificat, un bloc d'ACL, une ligne de profil.

Intégration : API REST documentée (OpenAPI), topics MQTT documentés (`docs/contracts.md`), webhook sortant optionnel
pour les incidents, export CSV.

## 11. Fabrication et vidéo

Le boîtier n'abrite que l'ESP32-S3 et ses capteurs : il est plus petit et s'imprime plus vite. Alimentation par un câble
USB depuis le PC serveur ou un chargeur 5 V. Façade : fenêtre de l'écran LCD, dôme PIR, LED d'état visible, gravure laser.
Couvercle : feuille de cuivre tactile. Aération pour le MQ-2 ; le DHT11 loin de lui. La webcam, branchée au PC, est posée près du boîtier.

Vidéo « Sentinel Drop » : accroche, boîtier, incrustation (dashboard, YOLO, Sentinel Score), outro ; 1080 × 1920,
59 s maximum.

## 12. Assemblage et contrôles

| Jour | Assemblage | Contrôle du soir |
| --- | --- | --- |
| Lundi | PC serveur préparé, Wi-Fi de table, socle Docker ; capteurs câblés sur l'ESP32-S3 ; CA générée | Vraies valeurs reçues sur 1883 |
| Mardi | TLS, API, base, dashboard v1 ; firmware v1 (tâches, garde locale, tampon) ; YOLO mesuré ; Brain prototypé | Go / no-go à 18 h : vraie mesure au dashboard en TLS |
| Mercredi | Brain et vision en production, Réglages, TLS mutuel ; boîtier assemblé ; captures et tournage | Démo complète jouée sans intervention, redémarrage du PC répété |
| Jeudi | Gel du code, tag v1.0, pentest, rendus | Livrables déposés |
| Vendredi | Allumage 10 minutes avant, simulateur en secours | Soutenance |

Critères du go / no-go de mardi : latence YOLO sous 100 ms sur le PC serveur, stack complète stable,
télémétrie TLS reçue. Si un critère échoue : réduction de la vision (taille d'image, images par seconde).

**Socle d'abord, extensions ensuite.** Le socle (flux TLS de bout en bout, garde locale, Brain couches 1 à 3, vision
avec zone) doit tourner mercredi midi. Les extensions (TLS mutuel, détection cyber complète, webhook, rôdeur) ne
s'ajoutent que si le socle est stable.

## 13. Ce qui fait la différence

- Un boîtier **qui reste vigilant sans réseau** et ne perd aucune mesure.
- Une détection **à l'échelle industrielle** : CUSUM, Isolation Forest et prévision combinés, réentraînés en continu.
- **Trois menaces dans un seul score**, avec des incidents nommés et expliqués.
- Un détecteur d'effraction **sans composant** grâce au tactile de l'ESP32-S3.
- La caméra se **surveille elle-même** (masquage, obscurité).
- Un produit **personnalisable par site** sans toucher au code, et un **redémarrage complet** répété et chronométré.
