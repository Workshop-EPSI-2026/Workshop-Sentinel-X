# Matrice de sécurité — Lisa

| Surface | Menace | Contre-mesure | Preuve prévue | État |
|---|---|---|---|---|
| Wi-Fi | Accès au réseau de table, brouillage | WPA2, phrase longue, SSID dédié, 2,4 GHz ; brouillage détecté par Brain (RSSI, déconnexions) | Configuration, incident « brouillage présumé » | |
| MQTT | Écoute, faux boîtier, abonné anonyme, rejeu, force brute | TLS 8883 puis TLS mutuel, pas d'anonyme, ACL par topic, `seq` + `boot_id` contrôlés, rafale d'accès refusés détectée | Wireshark, client sans certificat refusé, rejeu et force brute détectés | |
| API | Appels non authentifiés, payload malveillant, DoS | Clé d'API, authentification de l'interface, validation stricte, limitation de débit nginx | Tests de refus, incident cyber sur rafale 401/429 | |
| PC serveur | Ports exposés, accès au poste | Pare-feu Windows : 443, 8883 et NTP **seulement depuis 192.168.137.0/24** ; vision et 8884 jamais exposés ; compte Windows avec mot de passe, verrouillage de session ; Defender actif | `serveur-pc.ps1 -Action Verifier`, Nmap avant/après | |
| Docker | Évasion, exposition de la BDD | Non root, no-new-privileges, capacités retirées, lecture seule, réseau interne pour la base, 2 ports publiés | `docker compose config`, Nmap | |
| Boîtier | Ouverture, vol des secrets | Effraction tactile, secrets hors dépôt, compte à droits minimaux, certificat révocable | Démo d'ouverture, ACL | |
| Caméra | Masquage, aveuglement, image figée, rejeu | Détection d'image uniforme, de faible luminosité et d'image figée ; `seq` + `boot_id` sur les messages vision ; caméra muette après une détection = sabotage | Incident « sabotage » en démo | |
| Vie privée | Biométrie, conservation d'images | **Aucune reconnaissance faciale** : badges ArUco ; pas d'enregistrement vidéo, seulement des résumés (personnes, zone) en base | Contrat vision, schéma de la base | |
| Dépôt | Fuite de secrets | `.gitignore`, gitleaks en CI | Rapport gitleaks | |

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
