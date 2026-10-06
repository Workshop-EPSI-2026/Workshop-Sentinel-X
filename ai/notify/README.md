# Notifications (`ai/notify`) — voix et mails

Service qui tourne **sur le PC serveur** (pas dans Docker : il a besoin des haut-parleurs). `tools\demarrer.ps1` le
lance avec la vision, dans une fenêtre réduite « Sentinel-X notifications ».

| Quand | Annonce vocale | Mail aux propriétaires du site |
| --- | --- | --- |
| Intrus (personne non autorisée dans la zone depuis 3 s, ou vue + PIR), rôdeur | « Intrus détecté. », « Personne suspecte dans la zone. » (« Intrusion présumée. » si ajoutée dans `types`) | Photo de la caméra **au moment de l'alerte**, date, heure, explication de Brain |
| Badge hors de ses horaires | « Badge présenté hors de ses horaires. » | Photo, nom du badge, horaires |
| Caméra masquée | « Caméra masquée. » | **Dernière image avant le masquage** (montre souvent qui l'a masquée) |
| Caméra rétablie | « Caméra rétablie. » | Durée du masquage, image actuelle |
| Sabotage du boîtier, fuite de gaz, incendie, attaque cyber, brouillage | Phrase dédiée | Explication, gravité, délai avant le seuil critique |

Un incident nouveau, ou dont la gravité monte, est annoncé tout de suite ; une répétition, au plus une fois toutes les
`cooldown_s` secondes. Si le PC n'a pas Internet, les mails attendent dans une file et partent au retour du réseau.

| Fichier | Rôle |
| --- | --- |
| `app/rules.py` | Quelles alertes annoncer, phrases, anti-répétition, caméra masquée puis rétablie (sans entrée/sortie) |
| `app/speech.py` | Voix hors ligne : synthèse vocale de Windows (voix française si installée, précédée d'un bip) ; espeak-ng sous Linux |
| `app/mailer.py` | Mail texte + HTML, photo intégrée et jointe, SMTP avec file d'attente et nouvel essai |
| `app/main.py` | Service : MQTT (`sentinel/brain/alert`, `sentinel/+/vision`, `sentinel/site/config`), images de la vision |
| `tests/test_notify.py` | Tests sans broker, sans haut-parleur, sans serveur de mail (lancés par la CI) |

## Réglages

**Mails** (dans `infra\.env`, jamais commité) :

```ini
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=alertes.sentinelx@gmail.com
SMTP_PASSWORD=xxxx xxxx xxxx xxxx      # mot de passe d'application Google, pas celui du compte
SMTP_FROM=alertes.sentinelx@gmail.com
NOTIFY_TO=proprietaire1@exemple.fr, proprietaire2@exemple.fr
```

Gmail : compte Google › Sécurité › Validation en deux étapes (activée) › **Mots de passe des applications**.
Sans `SMTP_HOST`, seules les annonces vocales fonctionnent (le journal l'indique).

**Comportement** : section `notifications` du profil de site (`config/site.example.yml`, puis page Réglages du
dashboard, appliquée sans redémarrage) : `voice`, `email`, `recipients` (prioritaire sur `NOTIFY_TO`), `types`,
`cooldown_s`, `camera_masked_s`, `camera_restored_s`.

Compte MQTT `notify` (lecture seule : alertes, vision, profil), créé par `python tools\configurer.py`.

## Commandes (depuis `ai\notify`)

```powershell
..\..\.venv\Scripts\python.exe -m app.main --env ..\..\infra\.env            # service (normalement lancé par demarrer.ps1)
..\..\.venv\Scripts\python.exe -m app.main --env ..\..\infra\.env --tester   # une annonce et un mail d'essai, puis arrêt
..\..\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Validé de bout en bout (broker, Brain, vision sur la vidéo de démonstration, serveur de mail de test) : agent badgé
hors horaires, intrusion présumée, rôdeur, caméra masquée puis rétablie « après 5 s de masquage », avec les bonnes
photos jointes ; profil modifié par l'API pris en compte à chaud.
