"""Diffusion temps réel vers les dashboards connectés en WebSocket."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

log = logging.getLogger("sentinel.hub")


class Hub:
    def __init__(self) -> None:
        self._clients: set[asyncio.Queue[dict[str, Any] | None]] = set()

    def subscribe(self) -> asyncio.Queue[dict[str, Any] | None]:
        q: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=500)
        self._clients.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any] | None]) -> None:
        self._clients.discard(q)

    def publish(self, type_: str, data: Any) -> None:
        message = {"type": type_, "data": data}
        for q in list(self._clients):
            try:
                q.put_nowait(message)
            except asyncio.QueueFull:
                # Client trop lent : on le déconnecte (il se reconnecte et recharge l'historique) plutôt que de bloquer les autres
                log.warning("Client WebSocket trop lent, déconnexion")
                self._clients.discard(q)
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                q.put_nowait(None)

    @property
    def count(self) -> int:
        return len(self._clients)
