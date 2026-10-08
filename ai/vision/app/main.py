"""Point d'entrée du service vision (tâche je1).

PC Windows (hors Docker, la webcam n'est pas accessible aux conteneurs) — depuis ai/vision, .venv activé :
    python -m app.main                               # webcam 0, broker localhost:8883 en TLS
    python -m app.main --source demo.mp4             # vidéo de démonstration en boucle
    python -m app.main --no-mqtt                     # vision seule, sans broker (réglage de la zone)
Variables lues : VISION_SOURCE, VISION_MODEL, MQTT_HOST, MQTT_PORT, MQTT_TLS, MQTT_CA, MQTT_USER,
MQTT_PASSWORD (ou MQTT_VISION_PASSWORD de infra/.env avec --env), SITE_PROFILE.
Linux / Raspberry Pi : même code dans un conteneur (infra/docker-compose.linux.yml).
"""
from __future__ import annotations

import argparse
import logging
import os
import signal
import threading

import uvicorn

from .config import VisionSettings
from .detector import YoloPersonDetector
from .faces import load_identifier
from .pipeline import VisionPipeline
from .service import Frames, Publisher, make_app, run_loop

log = logging.getLogger("vision")


def load_env_file(path: str) -> None:
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.split(" #")[0].strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Service vision Sentinel-X")
    ap.add_argument("--source", help="index de webcam (0), fichier vidéo ou URL ; défaut : VISION_SOURCE ou 0")
    ap.add_argument("--model", help="yolov8n.pt (PC) ou yolov8n_ncnn_model (Raspberry Pi), dans ai/vision/models")
    ap.add_argument("--profile", help="profil de site (défaut : config/site.example.yml)")
    ap.add_argument("--env", help="fichier .env à lire (ex. ../../infra/.env)")
    ap.add_argument("--no-mqtt", action="store_true", help="ne publie rien sur le broker")
    ap.add_argument("--no-loop", action="store_true", help="vidéo de démo : s'arrêter à la fin")
    ap.add_argument("--port", type=int, help="port HTTP du flux vidéo (défaut 8001)")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    if a.env:
        load_env_file(a.env)
        os.environ.setdefault("MQTT_PORT", "8883")            # depuis le PC : port publié des boîtiers
        if os.environ.get("MQTT_PORT") == "8884":
            os.environ["MQTT_PORT"] = "8883"
    s = VisionSettings.load(a.profile, source=a.source, model=a.model, http_port=a.port,
                            loop=False if a.no_loop else None, mqtt_enabled=False if a.no_mqtt else None)
    log.info("vision %s : source %s, modèle %s (%d px), zone %s", s.device_id, s.source, s.model_path,
             s.imgsz, s.zone)

    detector = YoloPersonDetector(s.model_path, s.imgsz, s.confidence)
    faces = load_identifier(s.models_dir, s.face_gallery_path, s.face_threshold) if s.face_recognition else None
    pipeline = VisionPipeline(s, detector, faces)
    publisher = Publisher(s)
    publisher.connect()
    frames = Frames()
    stop = threading.Event()

    server = uvicorn.Server(uvicorn.Config(make_app(frames, s), host=s.http_host, port=s.http_port,
                                           log_level="warning"))
    threading.Thread(target=server.run, daemon=True, name="http").start()
    log.info("flux vidéo : http://%s:%d/video", s.http_host, s.http_port)

    def shutdown(*_):
        stop.set()
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    try:
        run_loop(s, pipeline, publisher, frames, stop)
    finally:
        publisher.close()
        server.should_exit = True


if __name__ == "__main__":
    main()
