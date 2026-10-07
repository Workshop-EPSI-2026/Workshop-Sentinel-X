"""Pipeline vision : une image entre, un état (personnes, zone, badges, intégrité) et une image annotée sortent."""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field

import cv2
import numpy as np

from .analysis import BadgeReader, MotionGate, Persistence, PresenceTracker, Track, assign_badges, check_integrity
from .config import VisionSettings
from .detector import Detector

GREEN, RED, ORANGE, WHITE, BLACK = (60, 200, 60), (40, 40, 230), (0, 165, 255), (255, 255, 255), (0, 0, 0)


@dataclass
class VisionState:
    ts: float
    fps: float
    motion: bool
    brightness: float
    masked: bool
    low_light: bool
    frozen: bool
    persons: list[dict] = field(default_factory=list)
    yolo_ran: bool = False
    yolo_ms: float | None = None

    @property
    def zone_count(self) -> int:
        return sum(p["in_zone"] for p in self.persons)

    def signature(self) -> tuple:
        """Ce qui doit déclencher une publication immédiate quand ça change."""
        return (tuple(sorted((p["track_id"], p["in_zone"], p["badge"]) for p in self.persons)),
                self.masked, self.low_light, self.frozen)


class VisionPipeline:
    def __init__(self, settings: VisionSettings, detector: Detector):
        self.s, self.detector = settings, detector
        self.motion = MotionGate()
        self.badges = BadgeReader(settings.aruco_dictionary)
        self.presence = PresenceTracker(settings.zone)
        self.masked_p = Persistence(2.0)          # 2 s d'image uniforme avant de crier au masquage
        self.dark_p = Persistence(3.0)
        self.frozen_p = Persistence(10.0)
        self.prev_small: np.ndarray | None = None
        self.frame_times: deque[float] = deque(maxlen=30)
        self.frames = 0
        self.last_person_t = -1e9
        self.last_integrity = None

    def process(self, frame: np.ndarray, t: float | None = None) -> tuple[VisionState, np.ndarray]:
        t = time.time() if t is None else t
        self.frames += 1
        self.frame_times.append(t)
        fps = (len(self.frame_times) - 1) / (self.frame_times[-1] - self.frame_times[0]) \
            if len(self.frame_times) > 1 and self.frame_times[-1] > self.frame_times[0] else 0.0
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # intégrité : masquage, obscurité, image figée (même image renvoyée en boucle)
        integ = check_integrity(gray, self.s.low_light_threshold)
        self.last_integrity = integ                 # mesures brutes, lisibles dans /health (réglage sur place)
        masked = self.s.masking_detection and self.masked_p.update(integ.masked, t)
        low_light = self.dark_p.update(integ.low_light, t)
        small = cv2.resize(gray, (80, 60), interpolation=cv2.INTER_AREA)
        same = self.prev_small is not None and np.array_equal(small, self.prev_small)
        self.prev_small = small
        frozen = self.frozen_p.update(same, t)

        # mouvement, puis YOLO seulement si utile
        moving, _ = self.motion.update(gray)
        recent_person = t - self.last_person_t < 3.0
        run_yolo = not masked and (moving or recent_person or self.frames % self.s.yolo_every_n_frames == 0)
        yolo_ms = None
        if run_yolo:
            t0 = time.perf_counter()
            dets = self.detector.track(frame)
            yolo_ms = (time.perf_counter() - t0) * 1000
            seen_badges = self.badges.read(gray) if dets else []
            badge_map = assign_badges(seen_badges, {tid: box for tid, box, _ in dets})
            self.presence.update(dets, t, badge_map)
            if dets:
                self.last_person_t = t
        tracks = self.presence.visible(t)
        persons = [self._person(tr, t) for tr in tracks]
        state = VisionState(t, round(fps, 1), moving, round(integ.brightness, 1), masked, low_light, frozen,
                            persons, run_yolo, None if yolo_ms is None else round(yolo_ms, 1))
        return state, self.annotate(frame, state, tracks)

    def _person(self, tr: Track, t: float) -> dict:
        return {"track_id": tr.track_id, "in_zone": tr.in_zone, "dwell_s": round(tr.dwell(t), 1),
                "badge": tr.badge, "authorized": tr.badge in self.s.authorized_badges,
                "conf": round(tr.conf, 2), "box": [round(v, 3) for v in tr.box]}

    # ------------------------------------------------------------------ image annotée (/video)
    def annotate(self, frame: np.ndarray, st: VisionState, tracks: list[Track]) -> np.ndarray:
        img = frame.copy()
        h, w = img.shape[:2]
        zone = np.array([[int(x * w), int(y * h)] for x, y in self.s.zone], np.int32)
        overlay = img.copy()
        cv2.fillPoly(overlay, [zone], (40, 40, 160) if st.zone_count else (60, 60, 60))
        img = cv2.addWeighted(overlay, 0.18, img, 0.82, 0)
        cv2.polylines(img, [zone], True, RED if st.zone_count else WHITE, 2)
        for tr in tracks:
            x1, y1, x2, y2 = (int(tr.box[0] * w), int(tr.box[1] * h), int(tr.box[2] * w), int(tr.box[3] * h))
            ok = tr.badge in self.s.authorized_badges
            color = GREEN if ok else (RED if tr.in_zone else ORANGE)
            cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
            label = f"#{tr.track_id}"
            if tr.badge is not None:
                label += f" badge {tr.badge}" + (f" {self.s.authorized_badges[tr.badge]}" if ok else " inconnu")
            if tr.in_zone:
                label += f" {tr.dwell(st.ts):.0f}s"
            self._label(img, label, (x1, max(18, y1 - 6)), color)
        status = f"{self.s.device_id}  {st.fps:.0f} img/s  {len(tracks)} pers.  zone : {st.zone_count}"
        self._label(img, status, (8, 22), BLACK, WHITE)
        for i, (flag, text) in enumerate(((st.masked, "CAMERA MASQUEE"), (st.low_light, "FAIBLE LUMINOSITE"),
                                          (st.frozen, "IMAGE FIGEE"))):
            if flag:
                self._label(img, text, (8, h - 14 - 26 * i), RED, WHITE, scale=0.8)
        return img

    @staticmethod
    def _label(img, text, org, bg, fg=WHITE, scale=0.5) -> None:
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 1)
        x, y = org
        cv2.rectangle(img, (x - 2, y - th - 4), (x + tw + 2, y + 4), bg, -1)
        cv2.putText(img, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, fg, 1, cv2.LINE_AA)
