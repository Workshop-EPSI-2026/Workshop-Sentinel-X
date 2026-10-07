# Sentinel-X — Architecture v3 (PC serveur)

> Matériel : ESP32-S3 N16R8, DHT11, module MQ-2, PIR HW-416-B, webcam USB, **PC portable sous Windows 11**.
> Décision d'équipe : le PC est le serveur (Option B du sujet : « PC serveur local, Raspberry Pi ou PC portable »).
> La solution reste portable telle quelle sur un serveur Linux ou un Raspberry Pi 5 (section 13).
> Les schémas illustrés se trouvent dans le document d'architecture partagé de l'équipe.

## 1. Synthèse

Sentinel-X est un système de détection **multicouche et autonome**. Le boîtier ne se contente pas de transmettre des
mesures : il raisonne déjà localement, garde ses données quand le réseau tombe et déclenche une alarme réflexe même si
le serveur est éteint. Sur le PC serveur, deux IA travaillent ensemble : la **vision** voit (qui, où, depuis combien de
temps, quel badge) et **Sentinel Brain** décide, en fusionnant trois domaines de menace — environnement, intrusion
physique, cyberattaque — en un score unique, avec une explication en langage clair pour chaque alerte.

| Décision | Choix |
| --- | --- |
| Boîtier | ESP32-S3 N16R8 (2 cœurs, 8 Mo de PSRAM, crypto matérielle, capteurs tactiles intégrés) |
| Serveur | N'importe quel PC portable Windows de l'équipe qui passe `verifier-serveur.cmd` : point d'accès Wi-Fi, Docker Desktop (broker, base, API, dashboard, Brain), vision sur la webcam |
| Secours | Un deuxième PC de l'équipe, même dépôt et même procédure, bascule en moins de 10 minutes ; vidéo de démonstration si la webcam lâche |
| Communication | MQTT : 1883 authentifié pour le socle, TLS 8883 ensuite, TLS mutuel (certificat par équipement) en cible |
| Détection capteurs | 4 couches : qualité des données, par capteur (CUSUM décorrélé + vitesse de montée), multivariée (Isolation Forest), prévision (Holt) |
| Vision | YOLOv8n + suivi ByteTrack, zone interdite, temps de présence, badges ArUco (sans biométrie), caméra masquée / sombre / figée |
| Personnalisation | Profil de site (`config/site.example.yml`) modifiable à chaud, appliqué au boîtier, à Brain et à la vision |
| Données | PostgreSQL 16, schéma qui garde `seq`, `boot_id` et l'heure de réception (rejouable, recalibrable) |

Principes : **autonomie à trois niveaux**, **sécurité dès le socle**, **aucune dépendance à Internet le jour de la
démo**, **chaque alerte expliquée**, **un seul fichier de configuration par site**, **aucune donnée biométrique**.

## 2. Matériel réel et exploitation maximale

| Composant | Capacités exploitées | Limites | Parade |
| --- | --- | --- | --- |
| ESP32-S3 N16R8 | 2 cœurs (FreeRTOS), 8 Mo de PSRAM pour un tampon de plusieurs heures, crypto matérielle (TLS mutuel), entrées tactiles, LED RGB | Broches réservées : 0, 3, 45, 46, 19-20, 35-37, 43-44 ; ADC avec Wi-Fi : GPIO 1 à 10 ; **Wi-Fi 2,4 GHz seulement** | Brochage figé dans `firmware/include/pins.h` ; point d'accès forcé en 2,4 GHz |
| DHT11 | Température et humidité | ±2 °C, pas de 1 °C, 1 lecture/s | Lissage avant toute pente, le gaz porte la détection fine |
| MQ-2 (module) | Millivolts et ratio sur ligne de base apprise ; sortie DO en seuil matériel | Préchauffage, sortie 5 V, pas de ppm sans étalon | Ponts diviseurs, ligne de base apprise, on parle de « ratio » |
| PIR HW-416-B | Mouvement jusqu'à ~7 m, comptage par minute | Temps mort, sensible à la chaleur | Cavalier H, fusion avec la vision |
| PC portable (serveur) | Processeur x86 : YOLOv8n en PyTorch à ~40 ms par image (320 px) ; mémoire largement suffisante ; point d'accès Wi-Fi intégré | Docker Desktop n'accède pas à la webcam ; mises à jour et veille de Windows | Vision hors Docker ; mode Avion du Wi-Fi désactivé, veille désactivée pendant la démo |
| Webcam USB (sur le PC) | Vision ; contrôle d'intégrité | Éclairage, champ | Zone et seuils réglables, PIR en relais quand l'image est mauvaise |
| LCD 1602, buzzer, LEDs | Affichage de l'état sur le boîtier ; alarme sonore et visuelle | LCD sans module I2C : 6 broches, contraste à régler | Mode 4 bits, RW à la masse, résistance fixe de contraste sur V0 |

Idée clé : **une feuille de cuivre collée à l'intérieur du couvercle, reliée à une entrée tactile de l'ESP32-S3,
devient un détecteur d'effraction gratuit**.

## 3. Architecture globale

```
                       Wi-Fi WPA2 2,4 GHz (point d'accès du PC, 192.168.137.0/24)
ESP32-S3 + capteurs ──────────────────────────────────────────────┐ MQTTS 8883
                                                                  ▼
PC serveur Windows 11 (192.168.137.1)
 ├─ webcam ─► vision (Python, hors Docker) ── MQTTS 8883 ──► ┌──────── Docker Desktop ────────────────────┐
 │            /video (127.0.0.1:8001)                          │ mosquitto  8883 publié · 8884 interne       │
 │                                                             │ anomaly    Sentinel Brain                   │
 │                                                             │ api        REST, WebSocket, ingestion       │
 │                                                             │ postgres   historique (réseau interne)      │
 │                                                             │ nginx      HTTPS 443 publié, dashboard,     │
 │                                                             │            /video relayé vers la vision     │
 └─ pare-feu Windows : 443, 8883, NTP depuis 192.168.137.0/24  └─────────────────────────────────────────────┘
Navigateur (PC ou poste du point d'accès) ── HTTPS 443 ──► nginx
```

Une mesure suit toujours le même chemin : l'ESP32-S3 la publie en MQTT chiffré au broker du PC, l'API la stocke et la
pousse au dashboard, Sentinel Brain la score. La vision publie ce qu'elle voit sur le même broker ; Brain croise les
deux. L'opérateur ne voit que nginx, en HTTPS.

### Autonomie à trois niveaux

| Niveau | Ce qui fonctionne | Exemple |
| --- | --- | --- |
| 1 · Boîtier seul | Mesures, garde locale, alarme réflexe (LED et buzzer), tampon de plusieurs heures en PSRAM | Wi-Fi brouillé : l'ESP sonne quand même et renvoie tout l'historique au retour du réseau |
| 2 · Boîtier + PC | Tout le système, sans Internet | Configuration de la démo |
| 3 · Intégration | API documentée, webhook sortant, export CSV, topics MQTT documentés | Remontée vers une supervision AetherCorp |

### Liens et ports

| Lien | Protocole | Port | Chiffré |
| --- | --- | --- | --- |
| ESP32-S3 vers broker | MQTT (télémétrie, événements, santé), retour des commandes et de la configuration | 8883 (1883 avant TLS) | Oui, TLS puis TLS mutuel |
| Vision vers broker | MQTT `sentinel/cam-01/vision` | 8883 (localhost) | Oui |
| Services Docker vers broker | MQTT | 8884 interne | Oui |
| Brain vers API | HTTP `POST /api/v1/alerts` dans Docker | 8000 interne | Non exposé |
| API vers base | PostgreSQL, réseau interne | 5432 interne | Non exposé |
| Navigateur vers nginx | HTTPS, WSS (`/ws`), MJPEG (`/video`) | 443 | Oui |
| ESP32-S3 vers PC | NTP (heure, indispensable au TLS) | 123/UDP | — |

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
| Buzzer | GPIO 10 | — | Si disponible |
| LED verte / rouge | GPIO 11 / 12 | — | Résistance série, si disponibles |
| LED RGB intégrée | GPIO 48 | — | Voyant d'état (38 sur certaines cartes) |

Alimentation : USB-C depuis le PC serveur ou un bloc 5 V / 2 A. Couleurs du voyant : **vert** surveillance, **bleu**
apprentissage, **orange** suspicion, **rouge** alarme, **violet** hors ligne (tampon actif), **blanc** maintenance.

### Firmware (FreeRTOS, deux cœurs)

| Tâche | Cœur | Rôle |
| --- | --- | --- |
| Capteurs | 1 | DHT11 toutes les 2 s, MQ-2 en mV calibrés, interruptions PIR, DO et effraction, température interne |
| Garde locale | 1 | Ligne de base EWMA par capteur, écart robuste, pente ; alarme réflexe sans le serveur ; échantillonnage à 500 ms pendant 60 s en cas de suspicion |
| Réseau | 0 | Wi-Fi, heure NTP du PC, MQTT TLS, QoS 1 pour les événements, tampon PSRAM rejoué avec les horodatages d'origine, dernière volonté |
| Santé | 0 | Toutes les 30 s : mémoire, RSSI, température de la puce, raison du redémarrage, tampon, déconnexions, erreurs TLS |

Modes : **APPRENTISSAGE** (10 min), **SURVEILLANCE**, **MAINTENANCE** (alarmes coupées). La configuration reçue sur
`sentinel/<id>/config` est appliquée immédiatement et enregistrée en NVS.

### Mise en place

1. PlatformIO, carte `esp32-s3-devkitc-1`, PSRAM activée ; téléverser par le port USB-C **COM**.
2. Câbler et tester chaque capteur seul, valeurs sur le moniteur série.
3. Ponts diviseurs du MQ-2, préchauffage dès le branchement, relever la valeur au repos.
4. Feuille de cuivre et seuil tactile.
5. Wi-Fi du point d'accès du PC (2,4 GHz), broker 192.168.137.1, MQTT en clair sur 1883 avec identifiants.
6. Tâches FreeRTOS, garde locale, voyant RGB, tampon PSRAM, santé.
7. TLS sur 8883 avec la CA embarquée, heure par le NTP du PC.
8. TLS mutuel : certificat client du boîtier fourni par Lisa.

**Fini quand** : Wi-Fi coupé 5 minutes, voyant violet, alarme locale fonctionnelle, et au retour du réseau toutes les
mesures arrivent sans trou, en TLS.

## 5. Bloc Réseau

Point d'accès mobile Windows : réseau **192.168.137.0/24** imposé par Windows, PC en **192.168.137.1**, ESP et
postes en DHCP. SSID `sentinel-x-gN`, 2,4 GHz, WPA2, phrase de passe de 20 caractères minimum, hors dépôt. Le PC doit
être relié à un réseau (Wi-Fi de l'école ou Ethernet) pour activer le point d'accès ; Sentinel-X ne s'en sert pas.
Plan B : un routeur de table réglé sur le même réseau, PC réservé en 192.168.137.1 (`docs/reseau.md`).

Ports ouverts (pare-feu Windows, uniquement depuis le réseau du point d'accès) : 443, 8883, 123/UDP ; 1883 avant TLS
seulement. Tout le reste est refusé. Préparation : `tools\serveur-pc.ps1` (administrateur).

## 6. Bloc Infrastructure : PC serveur et Docker Desktop

| Service | Rôle | Où | Port publié | Mémoire max | Profil |
| --- | --- | --- | --- | --- | --- |
| `mosquitto` | Bus MQTT, TLS, ACL ; 8883 boîtier et vision, 8884 services | Docker | 8883 | 64 Mo | socle |
| `postgres` | Historique, incidents, configuration | Docker (réseau interne) | aucun | 384 Mo | socle |
| `api` | REST, WebSocket, ingestion, configuration | Docker | aucun | 256 Mo | app |
| `nginx` | HTTPS, WSS, dashboard, limitation de débit, relais `/video` | Docker | 443 | 64 Mo | app |
| `anomaly` (Sentinel Brain) | Détection multicouche, fusion, incidents, score | Docker | aucun | 512 Mo | ai |
| vision | Webcam, YOLO, suivi, zone, badges, intégrité, `/video` | **PC, hors Docker** (127.0.0.1:8001) | aucun | ~1 Go | — |

Conteneurs : redémarrage automatique, contrôle de santé, sans root, `no-new-privileges`, capacités retirées, système
de fichiers en lecture seule, journaux limités. Le journal de Mosquitto est partagé en lecture seule avec Brain pour
détecter les accès refusés.

Pourquoi la vision hors Docker : sous Windows, Docker Desktop tourne dans une machine virtuelle WSL 2 qui ne voit pas
la webcam. La vision tourne donc dans le `.venv` du PC et nginx la joint par `host.docker.internal`. Sous Linux, la même
vision passe dans un conteneur (`docker-compose.linux.yml`).

### Mise en place

1. Choisir le serveur : **n'importe quel poste de l'équipe** qui passe `verifier-serveur.cmd` (mémoire ≥ 8 Go, 4 cœurs,
   15 Go libres, carte Wi-Fi, WSL 2 et Docker, webcam, YOLO ≥ 5 images/s). `installer.cmd` a déjà tout installé.
2. `tools\serveur-pc.ps1` en administrateur : pare-feu, NTP, point d'accès ; puis `python tools\doctor.py --serveur`.
   Le point d'accès donne toujours 192.168.137.1 au serveur : certificats et `secrets.h` restent valables quel que soit
   le poste choisi.
3. `infra\.env` depuis `.env.example`, comptes Mosquitto (`infra/mosquitto/README.md`).
4. Socle (Mosquitto + PostgreSQL, 1883), puis TLS (`MOSQUITTO_CONF=mosquitto.tls.conf`), puis profils `app` et `ai`.
5. Tout démarrer : `tools\demarrer.ps1` (stack + vision). Arrêter : `tools\demarrer.ps1 -Arreter`.
6. Répétition de bascule sur le PC de secours : moins de 10 minutes chronométrées.

## 7. Bloc Backend et Dashboard

| Route | Méthode | Rôle |
| --- | --- | --- |
| `/api/v1/alerts` | POST | Ingestion d'une alerte (Brain), clé d'API |
| `/api/v1/alerts` | GET | Incidents filtrés par statut, domaine, gravité |
| `/api/v1/alerts/{id}` | PATCH | Acquitter ou clore un incident |
| `/api/v1/telemetry?from=&device=` | GET | Historique paginé |
| `/api/v1/commands` | POST | Commande vers un boîtier (alarme, mode, recalibrage, redémarrage) |
| `/api/v1/config` | GET / PUT | Profil de site ; publié en message conservé aux boîtiers, à Brain et à la vision |
| `/api/v1/score` | GET | Scores courants par domaine |
| `/api/v1/health` | GET | Santé du PC, des conteneurs, des boîtiers et de la vision |
| `/ws` | WebSocket | Télémétrie, vision, scores, incidents en temps réel |

Base PostgreSQL : **créée par l'API** au démarrage (migrations de `api/app/db.py`, tâches c2 et c5) : `devices`,
`telemetry`, `events`, `device_health`, `scores`, `alerts` (cycle de vie ouvert → acquitté → résolu, un seul incident
actif par équipement et type, répétitions comptées), `commands`, `config_versions`, `audit_log`. Insertion idempotente
sur (`device_id`, `boot_id`, `seq`). L'API accepte tous les types d'incidents de Brain v3 et combine les scores par
équipement (boîtier, caméra) en une jauge : le maximum par domaine sur les équipements actifs.

**Notifications** (`ai/notify`, sur le PC car il faut les haut-parleurs) : annonce vocale (« Intrus détecté »,
« Caméra masquée », « Caméra rétablie »…) et mail aux propriétaires avec la photo du moment, la date et l'heure ; pour
un masquage, la dernière image avant le masquage. Réglages : section `notifications` du profil (page Réglages) et
SMTP dans `infra/.env`.

Vues du dashboard : **Supervision** (jauge Sentinel Score, courbes, voyant du boîtier), **Incidents** (explication,
acquittement), **Vision** (flux annoté, personnes, badges, état de la caméra), **Système** (santé de chaque brique),
**Réglages** (profil de site, sensibilités, horaires, zone, badges autorisés).

## 8. Bloc IA : vision et Sentinel Brain

### Vision (`ai/vision`)

| Étape | Méthode | Coût |
| --- | --- | --- |
| Mouvement | Soustraction de fond MOG2 sur image réduite ; YOLO ne tourne que s'il se passe quelque chose | < 1 ms |
| Personnes | YOLOv8n (PyTorch sur PC, NCNN sur Raspberry Pi), 320 px, classe personne | ~40 ms sur PC |
| Suivi | ByteTrack : un identifiant stable par personne, temps de présence | faible |
| Zone | Pieds de la personne dans le polygone du profil de site | négligeable |
| Badge | Marqueur ArUco imprimé, porté par l'agent ; associé à la personne qui le porte, gardé pendant tout le suivi | ~2 ms |
| Intégrité | Image uniforme ou noire (masquée), sombre mais texturée (faible luminosité), identique 10 s (figée) | < 1 ms |

Sortie : `sentinel/cam-01/vision` chaque seconde et à chaque changement, flux annoté `/video`.

### Sentinel Brain (`ai/anomaly`) — les quatre couches sur les capteurs

| Couche | Méthode | Ce qu'elle attrape |
| --- | --- | --- |
| 1 · Qualité des données | Plausibilité, capteur figé, `seq` + `boot_id`, horodatage | Capteur défaillant, message injecté ou rejoué (boîtier et caméra) |
| 2 · Par capteur | CUSUM décorrélé sur écart robuste (MAD) ; vitesse de montée comparée à l'enveloppe saine | Dérives lentes ; montées rapides (fuite, feu) avant tout seuil |
| 3 · Multivariée | Isolation Forest sur fenêtres de 60 s | Combinaisons inhabituelles |
| 4 · Prévision | Holt à pas variable | « Niveau critique atteint dans 3 min » |

Le CUSUM est la méthode de référence de la maîtrise statistique des procédés. Les capteurs étant très autocorrélés
(le MQ-2 « respire » sur ~90 s), il compte une observation indépendante par `tau_d` secondes, et il est doublé d'un
détecteur de **vitesse de montée** (principe des détecteurs thermovélocimétriques). Réglages calibrés sur 24 h de régime
normal et mesurés sur d'autres données : `ai/anomaly/notebooks/01-prototype.ipynb`.

### Fusion et incidents

Trois scores de 0 à 100 — **environnement**, **physique**, **cyber** — et un **Sentinel Score** global (maximum pondéré).
Le domaine physique d'un boîtier inclut ce que voit la caméra. Règles de corrélation :

| Incident | Condition |
| --- | --- |
| Intrusion confirmée | Personne sans badge autorisé dans la zone **et** PIR à moins de 5 s, **ou** seule dans la zone depuis `vision_confirm_s` (3 s), même sans PIR |
| Intrusion présumée | Vision seule pendant moins de `vision_confirm_s` (3 s ; au-delà : intrusion confirmée), PIR seul quand la caméra est aveugle, ou personne non badgée accompagnée d'un agent |
| Rôdeur | Personne sans badge dans la zone depuis plus de 20 s |
| Présence autorisée | Agent badgé dans la zone, dans ses horaires (information, pas d'alarme) |
| Présence à vérifier | Badge connu mais hors de ses horaires |
| Sabotage | Boîtier ouvert, caméra masquée, ou caméra muette moins de 60 s après une détection |
| Risque incendie | Hausse du gaz et de la température ensemble |
| Fuite de gaz | CUSUM ou vitesse de montée sur le gaz, température stable |
| Dérive thermique | Température seule en dérive, gaz stable |
| Brouillage Wi-Fi présumé | Chute du RSSI puis boîtier hors ligne |
| Attaque cyber | Rejeu, horodatage falsifié, rafale de 5 accès MQTT refusés en 60 s (avec l'adresse), rafale 401/429 sur l'API |
| Capteur défaillant / caméra dégradée | Valeur figée ou impossible ; image trop sombre ; caméra hors ligne sans détection récente |

Quand la caméra est masquée, sombre ou hors ligne, le PIR devient plus sensible et fait foi. Quand elle voit la scène,
c'est elle qui porte l'incident (pas de doublon). Un incident ouvert absorbe ses suites ; il ne déclenche une nouvelle
alerte que s'il s'aggrave (fuite → incendie, présumée → confirmée). Chaque incident porte son **explication**.

### Apprentissage et adaptation

- **Apprentissage** de 10 minutes par boîtier (`learning_minutes` du profil) : lignes de base et enveloppes.
- **Réentraînement** de l'Isolation Forest toutes les 30 min sur les fenêtres sans incident.
- **Sensibilités par domaine**, horaires des badges et zone réglables à chaud (`sentinel/site/config`).

**Indicateurs à présenter** : avance sur les seuils bruts, fausses alarmes sur 24 h normales, délai PIR → intrusion
confirmée, latence YOLO et images/s sur le PC.

## 9. Bloc Cybersécurité

| Surface | Contre-mesure | Preuve |
| --- | --- | --- |
| Wi-Fi | WPA2, phrase longue, réseau isolé du point d'accès | Configuration |
| MQTT | TLS, puis TLS mutuel (un certificat par équipement, identité = nom d'utilisateur) ; ACL par topic ; 1883 fermé | Wireshark clair contre chiffré ; client sans certificat refusé ; force brute détectée |
| API | HTTPS, clé d'API, validation stricte, limitation de débit, authentification de l'interface | Payload invalide rejeté, appel sans clé refusé |
| PC serveur | Pare-feu Windows (443, 8883, NTP depuis le point d'accès seulement), vision et 8884 jamais exposés, démon Docker non exposé | Nmap avant et après |
| Docker | Non root, `no-new-privileges`, lecture seule, base interne, 2 ports publiés | `docker compose config`, Nmap |
| Boîtier | Secrets hors dépôt, compte à droits minimaux, effraction détectée | ACL, démo d'ouverture |
| Vie privée | Aucune biométrie (badges ArUco), pas d'enregistrement vidéo | Contrat vision, schéma de la base |
| Détection | Accès refusés, rejeu, brouillage et rafales d'API transformés en incidents cyber | Incident visible pendant le pentest |
| Dépôt | `.gitignore`, gitleaks en CI | Rapport gitleaks |

Le démarrage sécurisé et le chiffrement de la flash de l'ESP32-S3 sont **volontairement non activés** (fusibles
irréversibles) : présentés comme étape d'industrialisation.

### Mise en place

1. CA locale, certificat serveur (SAN : 192.168.137.1, 127.0.0.1, `localhost`, `sentinel-pc`, `mosquitto`,
   `host.docker.internal`) ; heure par le NTP du PC.
2. TLS sur Mosquitto, ACL ; fermeture de 1883 et de sa règle de pare-feu.
3. Certificats clients (`esp-01`, `vision`, `monitor`), puis `MOSQUITTO_CONF=mosquitto.mtls.conf`.
4. Durcissement du PC serveur, Nmap depuis un autre poste du point d'accès ; preuves dans `docs/preuves/`.
5. Avec Jeffrick : signaux cyber vers Sentinel Brain (accès refusés : déjà actifs ; rafales 401/429 de l'API).
6. Pentest croisé depuis un poste de l'équipe (Nmap, Wireshark, Metasploit en conteneur).

## 10. Personnalisation et intégration

Un site = un fichier de profil (`config/site.example.yml`) : capteurs actifs, seuils, sensibilités, plages horaires,
zone de la caméra, **badges autorisés et leurs horaires**, alarme locale. Le profil se modifie depuis la page Réglages ;
l'API le versionne, le publie en message conservé, et le boîtier, Brain et la vision l'appliquent sans redémarrage.
Ajouter un boîtier = un certificat, un bloc d'ACL, une ligne de profil. Ajouter un agent = un badge imprimé
(`ai/vision/tools/badges.py`) et une ligne de profil.

Intégration : API REST documentée (OpenAPI), topics MQTT documentés (`docs/contracts.md`), webhook sortant pour les
incidents, export CSV.

## 11. Fabrication et vidéo

Le boîtier n'abrite plus que l'ESP32-S3 et ses capteurs : plus petit, alimenté en USB-C. Façade : fenêtre du LCD 1602 (si
disponible), dôme PIR, LED d'état visible, gravure laser. Couvercle : feuille de cuivre tactile. Aération pour le MQ-2,
DHT11 éloigné de lui. Le PC et la webcam sont posés à côté, la webcam orientée vers la zone surveillée.

Vidéo « Sentinel Drop » : accroche, boîtier, incrustation (dashboard, flux vision annoté, Sentinel Score), outro ;
1080 × 1920, 59 s maximum.

## 12. Assemblage et contrôles

| Jour | Assemblage | Contrôle du soir |
| --- | --- | --- |
| Lundi | Capteurs câblés sur l'ESP32-S3 ; CA générée ; simulateur et prototype de Brain | Vraies valeurs reçues |
| Mardi | PC serveur prêt (pare-feu, point d'accès, Docker), socle puis TLS, API, base, dashboard v1 ; firmware v1 ; vision v1 ; YOLO mesuré | Go / no-go à 18 h : vraie mesure au dashboard en TLS |
| Mercredi | Brain et vision en production, Réglages, TLS mutuel ; boîtier assemblé ; captures et tournage | Démo complète jouée sans intervention, bascule sur le PC de secours répétée |
| Jeudi | Gel du code, tag v1.0, pentest, rendus | Livrables déposés |
| Vendredi | Allumage 10 minutes avant (veille et mises à jour Windows désactivées), simulateur et vidéo de démo en secours | Soutenance |

Critères du go / no-go de mardi : télémétrie TLS reçue au dashboard, YOLO sous 100 ms à 320 px sur le PC, vision
publiée au broker, stack complète démarrée par `tools\demarrer.ps1`. Si un critère échoue : bascule sur le PC de secours,
ou vision sur la vidéo de démonstration.

**Socle d'abord, extensions ensuite.** Le socle (flux TLS de bout en bout, garde locale, Brain couches 1 à 3, vision
avec zone) doit tourner mercredi midi. Les extensions (TLS mutuel, badges, détection cyber complète, webhook) ne
s'ajoutent que si le socle est stable.

## 13. Portabilité : serveur Linux ou Raspberry Pi 5

Rien n'est propre à Windows dans le code. Sur un serveur Linux ou un Raspberry Pi 5 (arm64) :

1. Docker Engine, dépôt cloné, `infra/.env`, `passwd`, certificats.
2. `COMPOSE_FILE=docker-compose.yml:docker-compose.linux.yml` : la vision passe dans un conteneur avec
   `/dev/video0`, nginx la joint par le réseau Docker.
3. Raspberry Pi : modèle NCNN (`ai/vision/tools/benchmark.py --ncnn`, `VISION_MODEL=yolov8n_ncnn_model`).
4. Point d'accès `nmcli` et NTP `chrony` à la place des réglages Windows ; même réseau 192.168.137.0/24 pour que l'ESP
   ne voie aucune différence. Contrôle : `python3 tools/doctor.py --linux`.

## 14. Ce qui fait la différence

- Un boîtier **qui reste vigilant sans réseau** et ne perd aucune mesure.
- Une détection **à l'échelle industrielle** : CUSUM, vitesse de montée, Isolation Forest et prévision, calibrés et mesurés.
- **Deux IA qui se complètent** : la vision voit, Brain décide ; PIR et caméra se confirment ou se relaient.
- **Des agents reconnus sans biométrie** (badges ArUco), avec leurs horaires.
- **Trois menaces dans un seul score**, avec des incidents nommés et expliqués.
- Un détecteur d'effraction **sans composant** grâce au tactile de l'ESP32-S3 ; une caméra qui **se surveille elle-même**.
- Un produit **personnalisable par site** sans toucher au code, démarré **en une commande**, portable sur Raspberry Pi.
