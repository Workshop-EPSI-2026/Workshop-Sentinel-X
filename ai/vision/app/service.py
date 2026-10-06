"""Service vision : capture, pipeline, publication MQTT, flux vidéo HTTP.

Sorties
  MQTT  sentinel/<cam>/vision   résumé toutes les secondes, et tout de suite quand la scène change
        sentinel/<cam>/status   online / offline (dernière volonté), message conservé
  HTTP  /health, /video (MJPEG annoté, relayé par nginx en HTTPS), /snapshot.jpg
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import threading
import time

import cv2
import numpy as np
import paho.mqtt.client as mqtt
from fastapi import FastAPI, Response
from fastapi.responses import StreamingResponse

from .config import VisionSettings
from .pipeline import VisionPipeline, VisionState

log = logging.getLogger("vision")


class Publisher:
    """Publie l'état de la caméra sur MQTT, au format du contrat (seq + boot_id contre le rejeu)."""

    def __init__(self, s: VisionSettings):
        self.s = s
        self.base = f"sentinel/{s.device_id}"
        self.boot_id = secrets.token_hex(4)
        self.seq = 0
        self.last_sig: tuple | None = None
        self.last_pub = 0.0
        self.client: mqtt.Client | None = None
        self.published = 0

    def connect(self) -> None:
        if not self.s.mqtt_enabled:
            return
        c = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                        client_id=f"vision-{self.s.device_id}-{self.boot_id}")
        c.username_pw_set(self.s.mqtt_user, self.s.mqtt_password)
        if self.s.mqtt_tls:
            c.tls_set(ca_certs=self.s.mqtt_ca, certfile=os.environ.get("MQTT_CERT"),
                      keyfile=os.environ.get("MQTT_KEY"))
        c.will_set(f"{self.base}/status", "offline", qos=1, retain=True)
        c.on_connect = self._on_connect
        c.reconnect_delay_set(1, 30)
        try:
            c.connect_async(self.s.mqtt_host, self.s.mqtt_port, keepalive=15)
        except (OSError, ValueError) as e:
            log.error("broker %s:%s injoignable : %s", self.s.mqtt_host, self.s.mqtt_port, e)
        c.loop_start()
        self.client = c

    def _on_connect(self, client, userdata, flags, rc, props=None) -> None:
        if rc == 0:
            client.publish(f"{self.base}/status", "online", qos=1, retain=True)
            log.info("connecté au broker %s:%s", self.s.mqtt_host, self.s.mqtt_port)
        else:
            log.error("connexion MQTT refusée : %s (identifiants ? ACL ?)", rc)

    def message(self, st: VisionState) -> dict:
        self.seq += 1
        return {"device_id": self.s.device_id, "seq": self.seq, "boot_id": self.boot_id, "ts": round(st.ts, 2),
                "fps": st.fps, "motion": st.motion, "brightness": st.brightness, "masked": st.masked,
                "low_light": st.low_light, "frozen": st.frozen, "zone_count": st.zone_count, "persons": st.persons}

    def maybe_publish(self, st: VisionState) -> dict | None:
        sig = st.signature()
        due = st.ts - self.last_pub >= self.s.publish_period_s
        changed = sig != self.last_sig and st.ts - self.last_pub >= 0.2      # au plus 5 messages par seconde
        if not (due or changed):
            return None
        self.last_sig, self.last_pub = sig, st.ts
        msg = self.message(st)
        if self.client is not None:
            self.client.publish(f"{self.base}/vision", json.dumps(msg, ensure_ascii=False), qos=0)
        self.published += 1
        return msg

    def close(self) -> None:
        if self.client is not None:
            self.client.publish(f"{self.base}/status", "offline", qos=1, retain=True).wait_for_publish(2)
            self.client.loop_stop()
            self.client.disconnect()


class Frames:
    """Dernière image annotée, partagée entre la boucle vision et le serveur HTTP."""

    def __init__(self):
        self.jpeg: bytes | None = None
        self.t = 0.0
        self.state: VisionState | None = None
        self.cond = threading.Condition()

    def put(self, img: np.ndarray, st: VisionState) -> None:
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 70])
        if ok:
            with self.cond:
                self.jpeg, self.t, self.state = buf.tobytes(), time.time(), st
                self.cond.notify_all()


def make_app(frames: Frames, s: VisionSettings) -> FastAPI:
    app = FastAPI(title="Sentinel-X vision", docs_url=None, redoc_url=None)

    @app.get("/health")
    def health():
        age = time.time() - frames.t if frames.t else None
        st = frames.state
        ok = age is not None and age < 5
        body = {"status": "ok" if ok else "degraded", "device_id": s.device_id, "last_frame_age_s": age,
                "fps": st.fps if st else None, "masked": st.masked if st else None,
                "persons": len(st.persons) if st else None}
        return Response(json.dumps(body), media_type="application/json", status_code=200 if ok else 503)

    @app.get("/snapshot.jpg")
    def snapshot():
        if frames.jpeg is None:
            return Response(status_code=503)
        return Response(frames.jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @app.get("/video")
    def video():
        def stream():
            seen = [0.0]                                      # date de la dernière image envoyée
            while True:
                with frames.cond:
                    frames.cond.wait_for(lambda: frames.t > seen[0], timeout=2.0)
                    jpeg, seen[0] = frames.jpeg, frames.t
                if jpeg:
                    yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
                time.sleep(0.08)                              # au plus ~12 images/s vers le navigateur
        return StreamingResponse(stream(), media_type="multipart/x-mixed-replace; boundary=frame")

    return app


def open_source(source: str) -> cv2.VideoCapture:
    if source.isdigit():
        backend = cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY     # DirectShow : ouverture rapide sous Windows
        cap = cv2.VideoCapture(int(source), backend)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        return cap
    return cv2.VideoCapture(source)


def run_loop(s: VisionSettings, pipeline: VisionPipeline, publisher: Publisher, frames: Frames,
             stop: threading.Event, max_frames: int | None = None) -> None:
    cap = open_source(s.source)
    is_file = not s.source.isdigit() and not s.source.startswith(("rtsp:", "http:", "https:"))
    period = 1.0 / (cap.get(cv2.CAP_PROP_FPS) or 15.0) if is_file else 0.0
    misses, n = 0, 0
    while not stop.is_set() and (max_frames is None or n < max_frames):
        t0 = time.time()
        ok, frame = cap.read()
        if not ok:
            if is_file and s.loop:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                continue
            misses += 1
            if is_file:
                log.info("fin de la vidéo %s", s.source)
                break
            if misses > 50:
                log.error("webcam perdue (%s), nouvelle ouverture", s.source)
                cap.release()
                time.sleep(1.0)
                cap, misses = open_source(s.source), 0
            continue
        misses, n = 0, n + 1
        state, img = pipeline.process(frame, t0)
        publisher.maybe_publish(state)
        frames.put(img, state)
        if period:
            time.sleep(max(0.0, period - (time.time() - t0)))
    cap.release()
