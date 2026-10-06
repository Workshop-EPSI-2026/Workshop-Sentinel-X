# Matrice de sécurité — Lisa

| Surface | Menace | Contre-mesure | Preuve prévue | État |
|---|---|---|---|---|
| Wi-Fi | Accès au réseau de table, brouillage | WPA2-AES, phrase longue, SSID dédié ; brouillage détecté par Brain (RSSI, déconnexions) | Configuration, incident « brouillage présumé » | |
| MQTT | Écoute, faux boîtier, abonné anonyme, rejeu | TLS 8883 puis TLS mutuel, pas d'anonyme, ACL par topic, `seq` + `boot_id` contrôlés | Wireshark, client sans certificat refusé, rejeu détecté | |
| API | Appels non authentifiés, payload malveillant, DoS | Clé d'API, authentification de l'interface, validation stricte, limitation de débit nginx | Tests de refus, incident cyber sur rafale 401/429 | |
| SSH | Force brute | Clé ed25519 uniquement, pas de root, fail2ban | `sshd -T`, Nmap | |
| Docker | Évasion, exposition de la BDD | Non root, no-new-privileges, réseau interne, 2 ports publiés | `docker compose config`, Nmap | |
| Boîtier | Ouverture, vol des secrets | Effraction tactile, secrets hors dépôt, compte à droits minimaux, certificat révocable | Démo d'ouverture, ACL | |
| Caméra | Masquage, aveuglement | Détection d'image uniforme et de faible luminosité | Incident « sabotage » en démo | |
| Dépôt | Fuite de secrets | `.gitignore`, gitleaks en CI | Rapport gitleaks | |

## Volontairement non activé
Démarrage sécurisé et chiffrement de la flash de l'ESP32-S3 : fusibles irréversibles. Présentés comme étape d'industrialisation.

## Outils d'audit
Nmap (reconnaissance et scan de ports), Wireshark (preuve du chiffrement), Metasploit (au moins une tentative documentée : module auxiliaire ou vérification de service exposé). Uniquement dans le cadre et le périmètre fixés par les coachs.

## Règles d'engagement du pentest
_À compléter avec la réponse des coachs (docs/coachs.md)._
