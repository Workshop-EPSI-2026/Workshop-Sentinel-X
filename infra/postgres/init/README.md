# Scripts d'initialisation PostgreSQL

Les fichiers `*.sql` placés ici sont exécutés **une seule fois**, au premier démarrage
(volume `pg-data` vide). Schéma à fournir par Jeffrick (tâche c5) : tables `telemetry`,
`alerts`, `commands`, nommées ex. `01-schema.sql`.

Pour rejouer l'initialisation : `docker compose down` puis `docker volume rm sentinel-x_pg-data`
(**efface les données** : exporter le CSV d'entraînement avant).
