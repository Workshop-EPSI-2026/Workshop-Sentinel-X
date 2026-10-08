"""Règles de site : badges autorisés et horaires, vision, sécurité du broker.

Lu dans le profil de site (config/site.example.yml), rechargé à chaud avec sentinel/site/config.
La caméra lit un badge (marqueur ArUco porté par l'agent) ou reconnaît un visage enrôlé (galerie locale du service
vision, membres consentants) ; Brain seul décide si la personne est autorisée, selon la liste blanche
(vision.authorized_badges, vision.authorized_faces) et les horaires du profil.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, time
from zoneinfo import ZoneInfo

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def _hhmm(s: str) -> time:
    h, m = str(s).strip().split(":")
    return time(int(h), int(m))


@dataclass(frozen=True)
class Badge:
    id: int
    name: str
    start: time | None = None          # plage horaire autorisée (None = toujours)
    end: time | None = None
    days: tuple[str, ...] = DAYS

    def allowed_at(self, local: datetime) -> bool:
        if DAYS[local.weekday()] not in self.days:
            return False
        if self.start is None or self.end is None:
            return True
        now = local.time()
        if self.start <= self.end:
            return self.start <= now <= self.end
        return now >= self.start or now <= self.end           # plage de nuit (22:00-06:00)

    @property
    def hours_txt(self) -> str:
        return "toute la journée" if self.start is None else f"{self.start:%H:%M}-{self.end:%H:%M}"


@dataclass(frozen=True)
class SitePolicy:
    timezone: str = "Europe/Paris"
    badges: dict[int, Badge] = field(default_factory=dict)
    faces: dict[str, Badge] = field(default_factory=dict)     # nom dans la galerie de visages -> horaires
    correlation_window_s: float = 5.0     # PIR et personne vue à moins de 5 s : intrusion confirmée
    loitering_s: float = 20.0             # présence prolongée dans la zone
    vision_confirm_s: float = 3.0         # inconnu dans la zone depuis 3 s : intrus confirmé sans PIR (0 = PIR exigé)
    camera_timeout_s: float = 15.0        # caméra silencieuse : hors ligne
    sabotage_window_s: float = 60.0       # caméra muette moins de 60 s après une détection : sabotage
    auth_failure_burst: int = 5           # accès MQTT refusés en 60 s : attaque
    auth_failure_window_s: float = 60.0

    @classmethod
    def from_profile(cls, profile: dict) -> SitePolicy:
        br = profile.get("brain", {}) or {}
        vi = profile.get("vision", {}) or {}
        def rule(b: dict, ident: int, default_name: str) -> Badge:
            start = end = None
            if b.get("hours"):
                a, z = str(b["hours"]).split("-")
                start, end = _hhmm(a), _hhmm(z)
            days = tuple(d.lower()[:3] for d in (b.get("days") or DAYS))
            return Badge(ident, str(b.get("name") or default_name), start, end, days)

        badges = {int(b["id"]): rule(b, int(b["id"]), f"badge {b['id']}")
                  for b in vi.get("authorized_badges", []) or []}
        faces = {str(f["name"]): rule(f, -1, str(f["name"])) for f in vi.get("authorized_faces", []) or []}
        d = cls()
        return cls(timezone=(profile.get("site", {}) or {}).get("timezone", d.timezone), badges=badges, faces=faces,
                   correlation_window_s=float(br.get("correlation_window_s", d.correlation_window_s)),
                   loitering_s=float(br.get("loitering_s", d.loitering_s)),
                   vision_confirm_s=float(br.get("vision_confirm_s", d.vision_confirm_s)),
                   camera_timeout_s=float(br.get("camera_timeout_s", d.camera_timeout_s)),
                   sabotage_window_s=float(br.get("sabotage_window_s", d.sabotage_window_s)),
                   auth_failure_burst=int(br.get("auth_failure_burst", d.auth_failure_burst)),
                   auth_failure_window_s=float(br.get("auth_failure_window_s", d.auth_failure_window_s)))

    def local(self, ts: float) -> datetime:
        return datetime.fromtimestamp(ts, ZoneInfo(self.timezone))

    def check_face(self, face: str | None, ts: float) -> tuple[bool, Badge | None, bool]:
        """Comme check_badge, pour un visage reconnu par la vision."""
        b = self.faces.get(str(face)) if face else None
        if b is None:
            return False, None, False
        ok = b.allowed_at(self.local(ts))
        return ok, b, not ok

    def check_badge(self, badge: int | None, ts: float) -> tuple[bool, Badge | None, bool]:
        """(autorisé maintenant, badge connu, badge connu mais hors horaires)."""
        if badge is None:
            return False, None, False
        b = self.badges.get(int(badge))
        if b is None:
            return False, None, False
        ok = b.allowed_at(self.local(ts))
        return ok, b, not ok


@dataclass
class Person:
    track_id: int
    in_zone: bool
    dwell_s: float
    badge: int | None
    authorized: bool = False              # décidé par Brain (liste blanche + horaires)
    off_hours: bool = False
    name: str | None = None
    face: str | None = None               # visage reconnu par la vision (indice, comme un badge)


@dataclass
class CameraBrain:
    """État d'une caméra vu par Brain."""
    first_rx: float
    last_rx: float
    online: bool = True
    offline_rx: float | None = None
    persons: list[Person] = field(default_factory=list)
    masked: bool = False
    masked_since: float | None = None
    low_light: bool = False
    brightness: float | None = None
    fps: float | None = None
    last_person_rx: float | None = None
    last_ts: float = 0.0
    phys_score: float = 0.0
    attack_rx: float | None = None
    attack_why: str = ""
    incidents: dict = field(default_factory=dict)
    buffered_count: int = 0


@dataclass
class BrokerWatch:
    """Accès refusés vus dans le journal de Mosquitto (identifiants faux, ACL, TLS)."""
    failures: deque = field(default_factory=lambda: deque(maxlen=500))
    incidents: dict = field(default_factory=dict)
    buffered_count: int = 0

    def burst(self, rx_ts: float, window_s: float) -> list[tuple[float, str, str | None]]:
        return [f for f in self.failures if rx_ts - f[0] <= window_s]
