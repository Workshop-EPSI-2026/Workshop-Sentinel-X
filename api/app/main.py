"""Point d'entrée : application FastAPI (REST sous /api/v1, WebSocket /ws), derrière nginx."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import secrets
import time
from contextlib import asynccontextmanager
from typing import Annotated, Any
from urllib.parse import parse_qs, urlsplit

from fastapi import FastAPI, Header, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from .auth import Operator, Service, log_refusal, same
from .db import Database
from .hub import Hub
from .models import AlertIn, AlertPatch, AlertStatus, CommandIn, ConfigIn, Domain
from .mqtt import MqttBridge
from .repo import Repo
from .service import Service as Core
from .service import ServiceError
from .settings import Settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s : %(message)s")
log = logging.getLogger("sentinel.api")

WS_AUTH_TIMEOUT_S = 5
VIDEO_TICKET_S = 60          # un ticket vidéo ouvre le flux pendant 60 s (le flux ouvert continue ensuite)
_VIDEO_KEY = secrets.token_bytes(32)   # propre à ce démarrage de l'API : un redémarrage invalide les tickets
TELEMETRY_PAGE = 1000


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings.from_env()
    db = Database(settings.database_url, settings.db_pool_size)
    await db.connect()  # attend PostgreSQL puis crée / met à jour tout le schéma
    repo = Repo(db)
    hub = Hub()
    core = Core(settings, repo, hub)
    await core.seed_config()
    core.mqtt = MqttBridge(settings, asyncio.get_running_loop(), core.handle_message, core.on_mqtt_connected)
    core.mqtt.start()
    purge = asyncio.create_task(core.purge_forever())
    app.state.settings, app.state.repo, app.state.hub, app.state.core = settings, repo, hub, core
    log.info("API prête")
    try:
        yield
    finally:
        purge.cancel()
        await core.mqtt.stop()
        await db.close()


app = FastAPI(title="Sentinel-X API", version="1.0.0", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")


@app.exception_handler(ServiceError)
async def service_error(_request: Request, e: ServiceError) -> JSONResponse:
    return JSONResponse(status_code=e.status, content={"detail": e.detail})


def core_of(request: Request) -> Core:
    return request.app.state.core


# ------------------------------------------------------------------------------------------------ supervision
@app.get("/api/v1/health")
async def health(request: Request, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    """Sans jeton (healthcheck Docker, curieux du réseau) : seulement « ok ». Le détail (processeur, mémoire,
    services, boîtiers) renseigne un attaquant : il est réservé à l'opérateur."""
    token = authorization[7:] if authorization and authorization.lower().startswith("bearer ") else ""
    if token and same(token, request.app.state.settings.operator_token):
        return await core_of(request).health()
    return {"status": "ok", "ts": time.time()}


# ------------------------------------------------------------------------------------------------- incidents
@app.post("/api/v1/alerts", status_code=201)
async def post_alert(alert: AlertIn, request: Request, _: Annotated[str, Service]) -> dict[str, Any]:
    """Ingestion d'une alerte (vision, Brain) : regroupée avec l'incident ouvert du même type, sinon nouvel incident."""
    return await core_of(request).raise_alert(alert)


@app.get("/api/v1/alerts")
async def get_alerts(
    request: Request, _: Annotated[str, Operator],
    status: AlertStatus | None = None, domain: Domain | None = None,
) -> list[dict[str, Any]]:
    return await request.app.state.repo.list_alerts(status, domain)


@app.patch("/api/v1/alerts/{alert_id}")
async def patch_alert(alert_id: int, patch: AlertPatch, request: Request, actor: Annotated[str, Operator]) -> dict[str, Any]:
    alert = await request.app.state.repo.update_alert_status(alert_id, patch.status)
    if alert is None:
        raise HTTPException(404, "Incident introuvable ou déjà résolu")
    await request.app.state.repo.audit(actor, f"alert_{patch.status}", str(alert_id))
    request.app.state.hub.publish("alert", alert)
    return alert


# ----------------------------------------------------------------------------------- historique, score, commandes
@app.get("/api/v1/telemetry")
async def get_telemetry(
    request: Request, _: Annotated[str, Operator],
    device: Annotated[str, Query(pattern=r"^[a-z0-9][a-z0-9-]{0,31}$")],
    from_: Annotated[float, Query(alias="from", ge=0)] = 0,
) -> dict[str, Any]:
    """Historique paginé : `next` est le `from` de la page suivante, null quand il n'y en a plus."""
    items, nxt = await request.app.state.repo.telemetry_page(device, from_, TELEMETRY_PAGE)
    return {"items": items, "next": nxt}


@app.get("/api/v1/score")
async def get_score(request: Request, _: Annotated[str, Operator]) -> dict[str, Any] | None:
    return await request.app.state.repo.latest_score()


@app.post("/api/v1/commands", status_code=202)
async def post_command(cmd: CommandIn, request: Request, actor: Annotated[str, Operator]) -> dict[str, Any]:
    return await core_of(request).send_command(cmd, actor)


# ---------------------------------------------------------------------------------------------- configuration
@app.get("/api/v1/config")
async def get_config(request: Request, _: Annotated[str, Operator]) -> dict[str, Any]:
    config = await request.app.state.repo.latest_config()
    if config is None:
        raise HTTPException(503, "Profil de site non initialisé")
    return config


@app.put("/api/v1/config")
async def put_config(body: ConfigIn, request: Request, actor: Annotated[str, Operator]) -> dict[str, Any]:
    """Nouvelle version du profil de site, publiée en message conservé aux boîtiers et à Sentinel Brain."""
    return await core_of(request).save_config(body.profile, actor)


# ------------------------------------------------------------------------------------------------- flux vidéo
def _video_sig(exp: int) -> str:
    return hmac.new(_VIDEO_KEY, f"video:{exp}".encode(), hashlib.sha256).hexdigest()[:32]


@app.post("/api/v1/video/ticket")
async def video_ticket(_: Annotated[str, Operator]) -> dict[str, Any]:
    """Une balise <img> ne peut pas envoyer d'en-tête Authorization : le dashboard demande un ticket court et le met
    dans l'URL du flux. Le jeton opérateur, lui, ne passe jamais dans une URL (journaux, historique du navigateur)."""
    exp = int(time.time()) + VIDEO_TICKET_S
    return {"ticket": f"{exp}.{_video_sig(exp)}", "expires": exp}


@app.get("/api/v1/video/check", status_code=204)
async def video_check(request: Request, x_original_uri: str | None = Header(default=None)) -> None:
    """Appelé par nginx (auth_request) avant d'ouvrir /video : 204 si le ticket est valide, sinon 401."""
    ticket = parse_qs(urlsplit(x_original_uri or "").query).get("ticket", [""])[0]
    exp_txt, _, sig = ticket.partition(".")
    if not (exp_txt.isdigit() and int(exp_txt) >= time.time() and same(sig, _video_sig(int(exp_txt)))):
        ip = request.headers.get("x-real-ip") or "?"
        await log_refusal(request.app.state.repo, ip, "flux vidéo : ticket absent ou expiré")
        raise HTTPException(401, "Ticket vidéo absent ou expiré")


# --------------------------------------------------------------------------------------------------- temps réel
@app.websocket("/ws")
async def ws(websocket: WebSocket) -> None:
    """Le client envoie {"type": "auth", "token": ...} en premier (jamais de jeton dans l'URL), reçoit {"type": "ready"}."""
    app_state = websocket.app.state
    await websocket.accept()
    try:
        first = json.loads(await asyncio.wait_for(websocket.receive_text(), WS_AUTH_TIMEOUT_S))
        token = first.get("token", "") if first.get("type") == "auth" else ""
    except (TimeoutError, ValueError, AttributeError, WebSocketDisconnect):
        token = ""
    if not token or not same(str(token), app_state.settings.operator_token):
        ip = websocket.headers.get("x-real-ip") or (websocket.client.host if websocket.client else "?")
        await log_refusal(app_state.repo, ip, "WebSocket : jeton absent ou invalide")
        await websocket.close(code=4401)
        return

    queue = app_state.hub.subscribe()
    try:
        await websocket.send_json({"type": "ready"})
        for st in await app_state.repo.device_statuses():  # état courant des boîtiers (le message MQTT conservé est déjà passé)
            await websocket.send_json({"type": "status", "data": {"device_id": st["device_id"], "status": st["status"], "ts": st["ts"]}})

        async def sender() -> None:
            while (message := await queue.get()) is not None:
                await websocket.send_json(message)

        async def drain() -> None:
            while True:  # lit pour détecter la fermeture ; le client n'envoie plus rien après l'authentification
                await websocket.receive_text()

        tasks = [asyncio.create_task(sender()), asyncio.create_task(drain())]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
        for t in done:
            t.exception()  # consomme l'exception (fermeture normale du client)
    except WebSocketDisconnect:
        pass
    finally:
        app_state.hub.unsubscribe(queue)
        try:
            await websocket.close()
        except RuntimeError:
            pass
