"""Authentification : jeton opérateur (interface) et clé d'API (services). Comparaisons à temps constant."""
from __future__ import annotations

import hmac
import time

from fastapi import Depends, Header, HTTPException, Request

from .repo import Repo

_last_audit = 0.0


def same(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


async def log_refusal(repo: Repo, ip: str, reason: str) -> None:
    """Refus tracé dans audit_log (signal cyber pour Sentinel Brain), au plus une ligne par seconde."""
    global _last_audit
    now = time.monotonic()
    if now - _last_audit < 1:
        return
    _last_audit = now
    await repo.audit("anonymous", "auth_refused", reason, {"ip": ip})


async def _deny(request: Request, reason: str) -> None:
    ip = request.headers.get("x-real-ip") or (request.client.host if request.client else "?")  # nginx pose X-Real-IP
    await log_refusal(request.app.state.repo, ip, reason)
    raise HTTPException(status_code=401, detail="Authentification requise", headers={"WWW-Authenticate": "Bearer"})


async def require_operator(request: Request, authorization: str | None = Header(default=None)) -> str:
    """Routes de l'interface : en-tête `Authorization: Bearer <OPERATOR_TOKEN>`."""
    token = authorization[7:] if authorization and authorization.lower().startswith("bearer ") else ""
    if not token or not same(token, request.app.state.settings.operator_token):
        await _deny(request, "jeton opérateur absent ou invalide")
    return "operator"


async def require_service(request: Request, x_api_key: str | None = Header(default=None)) -> str:
    """Routes des services (vision, Brain) : en-tête `X-API-Key`."""
    if not x_api_key or not same(x_api_key, request.app.state.settings.api_key):
        await _deny(request, "clé d'API absente ou invalide")
    return "service"


Operator = Depends(require_operator)
Service = Depends(require_service)
