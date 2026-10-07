"""Pont MQTT : reçoit les messages des boîtiers et de Brain, publie commandes et configuration.

paho-mqtt tourne dans son propre thread ; les messages sont remis à la boucle asyncio par une file bornée.
"""
from __future__ import annotations

import asyncio
import json
import logging
import ssl
from collections.abc import Awaitable, Callable
from typing import Any

import paho.mqtt.client as mqtt

from .settings import Settings

log = logging.getLogger("sentinel.mqtt")

SUBSCRIPTIONS = [
    "sentinel/+/telemetry",
    "sentinel/+/event",
    "sentinel/+/health",
    "sentinel/+/status",
    "sentinel/brain/score",
    "sentinel/+/vision",       # service vision (cam-01) : personnes, zone, état de la caméra -> dashboard en direct
]

Handler = Callable[[str, bytes], Awaitable[None]]


class MqttBridge:
    def __init__(self, settings: Settings, loop: asyncio.AbstractEventLoop, handler: Handler,
                 on_connected: Callable[[], Awaitable[None]]) -> None:
        self.settings = settings
        self.loop = loop
        self.handler = handler
        self.on_connected_cb = on_connected
        self.connected = False
        self.dropped = 0
        self._queue: asyncio.Queue[tuple[str, bytes]] = asyncio.Queue(maxsize=5000)
        self._task: asyncio.Task[None] | None = None

        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="sentinel-api", clean_session=True)
        c.username_pw_set(settings.mqtt_user, settings.mqtt_password)
        if settings.mqtt_tls:
            c.tls_set(ca_certs=settings.mqtt_ca, tls_version=ssl.PROTOCOL_TLS_CLIENT)
        c.reconnect_delay_set(min_delay=1, max_delay=15)
        c.on_connect = self._on_connect
        c.on_disconnect = self._on_disconnect
        c.on_message = self._on_message
        self.client = c

    # ------------------------------------------------------------------------------ thread paho
    def _on_connect(self, client: mqtt.Client, _userdata: Any, _flags: Any, reason: Any, _props: Any) -> None:
        if reason.is_failure:
            log.error("Connexion MQTT refusée : %s", reason)
            return
        for topic in SUBSCRIPTIONS:
            client.subscribe(topic, qos=1)
        self.connected = True
        log.info("MQTT connecté à %s:%s", self.settings.mqtt_host, self.settings.mqtt_port)
        asyncio.run_coroutine_threadsafe(self.on_connected_cb(), self.loop)

    def _on_disconnect(self, _client: mqtt.Client, _userdata: Any, _flags: Any, reason: Any, _props: Any) -> None:
        self.connected = False
        log.warning("MQTT déconnecté : %s", reason)

    def _on_message(self, _client: mqtt.Client, _userdata: Any, msg: mqtt.MQTTMessage) -> None:
        self.loop.call_soon_threadsafe(self._enqueue, msg.topic, bytes(msg.payload))

    # ------------------------------------------------------------------------------ boucle asyncio
    def _enqueue(self, topic: str, payload: bytes) -> None:
        try:
            self._queue.put_nowait((topic, payload))
        except asyncio.QueueFull:
            self.dropped += 1
            if self.dropped % 100 == 1:
                log.error("File MQTT pleine : %s messages abandonnés", self.dropped)

    async def _consume(self) -> None:
        while True:
            topic, payload = await self._queue.get()
            try:
                await self.handler(topic, payload)
            except Exception:  # un message défectueux ne doit jamais arrêter l'ingestion
                log.exception("Traitement du message %s impossible", topic)

    def start(self) -> None:
        self._task = asyncio.create_task(self._consume())
        self.client.connect_async(self.settings.mqtt_host, self.settings.mqtt_port, keepalive=30)
        self.client.loop_start()

    async def stop(self) -> None:
        self.client.disconnect()
        self.client.loop_stop()
        if self._task:
            self._task.cancel()

    def publish(self, topic: str, payload: dict[str, Any], retain: bool = False) -> bool:
        info = self.client.publish(topic, json.dumps(payload, separators=(",", ":")), qos=1, retain=retain)
        return info.rc == mqtt.MQTT_ERR_SUCCESS
