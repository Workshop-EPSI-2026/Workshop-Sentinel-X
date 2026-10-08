# Matrice de sécurité — Lisa

| Surface | Menace | Contre-mesure | Preuve prévue | État |
|---|---|---|---|---|
| Wi-Fi | Accès au réseau de table, brouillage | WPA2, phrase longue, SSID dédié, 2,4 GHz ; brouillage détecté par Brain (RSSI, déconnexions) | Configuration, incident « brouillage présumé » | |
| MQTT | Écoute, faux boîtier, abonné anonyme, rejeu, force brute | TLS 8883 puis TLS mutuel, pas d'anonyme, ACL par topic, `seq` + `boot_id` contrôlés, rafale d'accès refusés détectée | Wireshark, client sans certificat refusé, rejeu et force brute détectés | Anonyme et faux mot de passe refusés, 1883 fermé en mode TLS (`verifier_securite.py`) ; boîtier encore en clair tant que le firmware n'est pas en TLS (mo2) |
| API | Appels non authentifiés, payload malveillant, DoS | Clé d'API (services) et jeton opérateur (interface) non interchangeables, comparaison à temps constant, validation stricte (champ inconnu refusé), requêtes SQL paramétrées, limitation de débit nginx, santé détaillée réservée à l'opérateur, refus tracés dans `audit_log` | `api/tests/test_api.py` (16 tests en CI), `verifier_securite.py` (401, 429) | Testé |
| Dashboard et vidéo | Vol du jeton, script injecté, flux caméra regardé par un intrus du réseau | HTTPS seul, jeton en `sessionStorage` et jamais dans une URL (WebSocket : premier message), CSP stricte, anti-iframe, HSTS ; flux vidéo ouvert seulement avec un ticket de 60 s signé par l'API (nginx `auth_request`), hors des journaux | Tests du dashboard (`npm test`), `verifier_securite.py` | Testé |
| PC serveur | Ports exposés, accès au poste | Pare-feu Windows : 443, 8883 et NTP **seulement depuis 192.168.137.0/24** ; vision et 8884 jamais exposés ; compte Windows avec mot de passe, verrouillage de session ; Defender actif | `serveur-pc.ps1 -Action Verifier`, Nmap avant/après | |
| Docker | Évasion, exposition de la BDD | Non root, no-new-privileges, capacités retirées, lecture seule, réseau interne pour la base, 2 ports publiés | `docker compose config`, Nmap | |
| Commandes du boîtier | Commande forgée ou rejouée (couper l'alarme pendant une intrusion) | Seule l'API publie sur `sentinel/esp-01/cmd` (ACL), après authentification de l'opérateur ; le boîtier ignore toute commande de plus de 30 s ou déjà exécutée (`id`) | Rejeu d'une commande capturée : « commande ignorée » au moniteur série | Testé en simulation |
| Boîtier | Ouverture, vol des secrets | Effraction tactile, secrets hors dépôt, compte à droits minimaux, certificat révocable | Démo d'ouverture, ACL | |
| Caméra | Masquage, aveuglement, image figée, rejeu | Détection d'image uniforme, de faible luminosité et d'image figée ; `seq` + `boot_id` sur les messages vision ; caméra muette après une détection = sabotage | Incident « sabotage » en démo | |
| Vie privée | Biométrie, conservation d'images | **Aucune reconnaissance faciale** : badges ArUco ; pas d'enregistrement vidéo, seulement des résumés (personnes, zone) en base | Contrat vision, schéma de la base | |
| Dépôt | Fuite de secrets | `.gitignore`, gitleaks en CI | Rapport gitleaks | |

## Vérification automatique (preuve)

`python tools\verifier_securite.py --rapport docs\preuves\verification-securite.txt` sur le PC serveur, stack lancée :
secrets générés, mode MQTT, `ca.key` hors du serveur, aucun secret suivi par Git, certificat HTTPS de la CA locale,
en-têtes, refus de l'API sans jeton ou avec un faux jeton, limitation de débit (429), flux vidéo refusé sans ticket,
MQTT anonyme et faux mot de passe refusés, ports internes (base, API, broker des services, démon Docker) fermés.
Depuis le PC d'un autre membre connecté au point d'accès : `--hote 192.168.137.1` (pentest croisé). Le rapport masque
les secrets ; il ne fait que deux essais MQTT refusés, sous le seuil de détection de Sentinel Brain.

## Avant la démo

1. `python tools\configurer.py --refaire` : nouveaux comptes MQTT, clé d'API, jeton et certificats (la base, les mails
   et le mode sont conservés). Recopier le nouveau mot de passe `esp-01` et `certs.h` dans le firmware.
2. Si le boîtier joint le PC par une autre adresse que 192.168.137.1 : `python security\pki\pki.py --ip <adresse>`.
3. `python tools\configurer.py --mode tls` : 1883 fermé, boîtier en 8883 (`sentinel_lisa`, `MQTT_USE_TLS 1`).
4. Ranger `security\certs\ca.key` sur une clé USB (elle ne sert qu'à signer de nouveaux certificats).
5. `tools\serveur-pc.ps1 -Action PareFeu`, puis `python tools\verifier_securite.py` : 0 KO.

## Volontairement non activé
Démarrage sécurisé et chiffrement de la flash de l'ESP32-S3 : fusibles irréversibles. Présentés comme étape d'industrialisation.

## Durcissement du PC serveur (tâche li1)
`tools\serveur-pc.ps1 -Action PareFeu` crée les seules règles entrantes nécessaires. À vérifier en plus, à la main :
Docker Desktop sans exposition du démon (*Settings > General > Expose daemon on tcp://localhost:2375* **décoché**),
découverte réseau désactivée sur le réseau du point d'accès, BitLocker si disponible, aucun partage de fichiers.

## Outils d'audit
Nmap (reconnaissance et scan de ports), Wireshark (preuve du chiffrement), Metasploit (au moins une tentative
documentée : module auxiliaire `auxiliary/scanner/mqtt/connect` ou vérification de service exposé). Ils tournent sur le
poste d'un autre membre, connecté au point d'accès. Metasploit sans installation sous Windows :
`docker run --rm -it metasploitframework/metasploit-framework`. Uniquement dans le cadre et le périmètre fixés par les coachs.

## Règles d'engagement du pentest
_À compléter avec la réponse des coachs (docs/coachs.md)._
