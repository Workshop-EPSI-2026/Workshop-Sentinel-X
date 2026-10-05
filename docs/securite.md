# Matrice de sécurité — Lisa (tâche l2)

| Surface | Menace | Contre-mesure | Preuve prévue | État |
|---|---|---|---|---|
| Wi-Fi | Accès au réseau de table | WPA2-AES, phrase longue, SSID dédié | Configuration | |
| MQTT | Écoute, faux boîtier, abonné anonyme | TLS 8883, `allow_anonymous false`, ACL | Wireshark, client anonyme refusé | |
| API | Appels non authentifiés, payload malveillant, DoS | Clé d'API/JWT, validation stricte, limitation de débit | Tests refus | |
| SSH | Force brute | Clé ed25519 uniquement, pas de root | `sshd -T`, Nmap | |
| Docker | Évasion, exposition de la BDD | Non root, no-new-privileges, réseau interne, ports limités | `docker compose config`, Nmap | |
| Firmware | Extraction des secrets | `secrets.h` hors dépôt, compte MQTT à droits minimaux | ACL | |
| Dépôt | Fuite de secrets | `.gitignore`, gitleaks en CI | Rapport gitleaks | |

## Règles d'engagement du pentest
_À compléter avec la réponse des coachs (docs/coachs.md)._
