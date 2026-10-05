# Dashboard — responsable : Constantin (binôme graphiques : Jeffrick)

Compilé **sur un laptop** (`npm run build`), jamais de serveur de développement sur le Pi.
Le dossier `dist/` produit est servi par nginx (monté en lecture seule) : copier `dist/`
sur le Pi (`scp -r dist sentinel-pi:~/sentinel-x/dashboard/`) puis rien à redémarrer.

Appels : `/api/v1/...` en HTTPS, temps réel sur `wss://<pi>/ws`, vidéo sur `/video`
(même origine, donc pas de CORS à gérer).
