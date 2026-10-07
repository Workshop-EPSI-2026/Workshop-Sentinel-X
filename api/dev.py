"""Lance l'API sur un poste Windows (développement, hors Docker).

Sous Windows, uvicorn utilise par défaut la boucle « Proactor », que psycopg refuse en mode asynchrone ; ce lanceur
impose la boucle « Selector ». Le conteneur (Linux) n'en a pas besoin : il lance `uvicorn app.main:app` directement.

    cd api
    python dev.py            # http://127.0.0.1:8000, variables d'environnement : voir api/README.md
"""
import asyncio
import os

import uvicorn

if __name__ == "__main__":
    config = uvicorn.Config("app.main:app", host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8000")))
    asyncio.run(uvicorn.Server(config).serve(), loop_factory=asyncio.SelectorEventLoop)
