# Scripts d'initialisation PostgreSQL

**Le schéma n'est pas ici : il est créé par l'API** (`api/app/db.py`, migrations appliquées à chaque démarrage).
Ce dossier ne sert que pour des extensions ou des réglages PostgreSQL qui doivent exister avant l'API ; les
fichiers `*.sql` qu'on y place sont exécutés **une seule fois**, au premier démarrage (volume `pg-data` vide).
Tables et règles de conservation : `api/README.md`.

Pour rejouer l'initialisation : `docker compose down` puis `docker volume rm sentinel-x_pg-data`
(**efface les données** : exporter le CSV d'entraînement avant).
