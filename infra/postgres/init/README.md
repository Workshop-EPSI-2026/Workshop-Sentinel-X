# Scripts d'initialisation PostgreSQL

**Le schéma n'est pas ici : il est créé par l'API** (`api/app/db.py`, migrations appliquées à chaque démarrage).
Ce dossier ne sert que pour des extensions ou des réglages PostgreSQL qui doivent exister avant l'API ; les
fichiers `*.sql` qu'on y place sont exécutés **une seule fois**, au premier démarrage (volume `pg-data` vide).
Tables et règles de conservation : `api/README.md`.

Pour rejouer l'initialisation : `docker compose down` puis `docker volume rm sentinel-x_pg-data`
(**efface les données** : exporter le CSV d'entraînement avant).

## Export pour recalibrer Sentinel Brain (tâche je2)

Sur le PC serveur, quelques heures de mesures en mode surveillance :

```powershell
docker exec snx-postgres psql -U sentinel -d sentinel -c "\copy (select device_id, extract(epoch from ts) as ts, seq, boot_id, temp_c, hum_pct, gas_mv, gas_ratio, gas_do, pir, pir_count, mode, edge_score, replay from telemetry where mode = 'armed' order by ts) to '/tmp/telemetry.csv' with csv header"
docker cp snx-postgres:/tmp/telemetry.csv ai\anomaly\data\telemetry.csv
```
