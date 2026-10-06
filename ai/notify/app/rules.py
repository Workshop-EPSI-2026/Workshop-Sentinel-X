"""Règles des notifications : quelles alertes annoncer, avec quels mots, et quand se taire.

Aucune entrée/sortie ici (ni réseau ni son) : tout se teste sans broker, sans haut-parleur, sans serveur de mail.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Type d'incident de Sentinel Brain -> (phrase dite à voix haute, titre du mail)
PHRASES: dict[str, tuple[str, str]] = {
    "intrusion_confirmed": ("Intrus détecté.", "Intrus détecté"),
    "intrusion_suspected": ("Intrusion présumée.", "Intrusion présumée"),
    "loitering": ("Personne suspecte dans la zone.", "Personne suspecte dans la zone"),
    "presence_to_verify": ("Badge présenté hors de ses horaires.", "Présence à vérifier"),
    "sabotage": ("Sabotage détecté.", "Sabotage détecté"),
    "fire_risk": ("Risque d'incendie.", "Risque d'incendie"),
    "gas_leak": ("Fuite de gaz détectée.", "Fuite de gaz"),
    "cyber_attack": ("Attaque informatique détectée.", "Attaque informatique"),
    "jamming_suspected": ("Brouillage du Wi-Fi détecté.", "Brouillage suspecté"),
    "thermal_drift": ("Température anormale.", "Dérive de température"),
}
DEFAULT_TYPES = ("intrusion_confirmed", "intrusion_suspected", "loitering", "presence_to_verify", "sabotage",
                 "fire_risk", "gas_leak", "cyber_attack", "jamming_suspected")
PHYSICAL_TYPES = {"intrusion_confirmed", "intrusion_suspected", "loitering", "presence_to_verify", "sabotage"}
RANK = {"info": 0, "warning": 1, "critical": 2}
GRAVITE = {"info": "Information", "warning": "Alerte", "critical": "CRITIQUE"}


@dataclass
class Settings:
    """Section « notifications » du profil de site (config/site.example.yml), valeurs par défaut sûres."""
    voice: bool = True
    email: bool = True
    recipients: list[str] = field(default_factory=list)
    types: tuple[str, ...] = DEFAULT_TYPES
    cooldown_s: float = 120.0
    camera_masked_s: float = 0.0   # la vision confirme déjà le masquage pendant 2 s
    camera_restored_s: float = 3.0

    @classmethod
    def from_profile(cls, profile: dict | None) -> Settings:
        n = (profile or {}).get("notifications") or {}
        d = cls()
        return cls(voice=bool(n.get("voice", d.voice)), email=bool(n.get("email", d.email)),
                   recipients=[str(x) for x in n.get("recipients") or []],
                   types=tuple(n.get("types") or d.types), cooldown_s=float(n.get("cooldown_s", d.cooldown_s)),
                   camera_masked_s=float(n.get("camera_masked_s", d.camera_masked_s)),
                   camera_restored_s=float(n.get("camera_restored_s", d.camera_restored_s)))


@dataclass
class Notice:
    """Une notification à émettre : phrase, mail, et s'il faut joindre une image (et laquelle)."""
    kind: str                 # type d'incident, ou camera_masked / camera_restored
    device_id: str
    severity: str
    spoken: str
    subject: str
    lines: list[str]
    ts: float
    photo: str | None = None  # "now" (image actuelle), "before_mask" (dernière image avant masquage), None


class AlertRules:
    """Décide, pour chaque alerte de Brain, s'il faut parler et écrire : un incident nouveau ou dont la gravité
    monte est annoncé tout de suite ; une répétition seulement après cooldown_s."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.last: dict[tuple[str, str], tuple[float, int]] = {}   # (équipement, type) -> (instant, gravité)

    def on_alert(self, a: dict, now: float) -> Notice | None:
        kind, device, sev = str(a.get("type", "")), str(a.get("device_id", "?")), str(a.get("severity", "info"))
        if kind not in self.settings.types or kind not in PHRASES or RANK.get(sev, 0) < RANK["warning"]:
            return None
        key, rank = (device, kind), RANK[sev]
        prev = self.last.get(key)
        if prev and rank <= prev[1] and now - prev[0] < self.settings.cooldown_s:
            return None
        self.last[key] = (now, rank)
        spoken, title = PHRASES[kind]
        lines = [str(a.get("explanation", "")).strip(), f"Équipement : {device}",
                 f"Gravité : {GRAVITE.get(sev, sev)} · score {a.get('score', '?')}/100"]
        if a.get("eta_min") is not None:
            lines.append(f"Seuil critique prévu dans {float(a['eta_min']):.1f} min")
        return Notice(kind, device, sev, spoken, f"{GRAVITE.get(sev, sev)} — {title}", [x for x in lines if x],
                      float(a.get("ts") or now), photo="now" if kind in PHYSICAL_TYPES else None)


class CameraWatch:
    """Caméra masquée puis rétablie, à partir des messages de la vision (champ « masked », déjà confirmé 2 s par
    la vision) : une notification au début du masquage, une à la fin avec sa durée. Hystérésis pour ne pas
    clignoter."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.state: dict[str, dict] = {}

    def on_vision(self, msg: dict, now: float) -> Notice | None:
        cam = str(msg.get("device_id", "cam"))
        st = self.state.setdefault(cam, {"masked": False, "since": None, "masked_at": None})
        raw = bool(msg.get("masked"))
        if raw == st["masked"]:
            st["since"] = None                       # rien ne change : on oublie un début de transition
            return None
        if st["since"] is None:
            st["since"] = now
        wait = self.settings.camera_masked_s if raw else self.settings.camera_restored_s
        if now - st["since"] < wait:
            return None
        st["masked"], st["since"] = raw, None
        if raw:
            return self._masked(cam, st, now)
        dur = now - (st["masked_at"] or now)
        return Notice("camera_restored", cam, "info", "Caméra rétablie.", "Information — Caméra rétablie",
                      [f"La caméra {cam} voit de nouveau la scène, après {fmt_duration(dur)} de masquage.",
                       "Image jointe : la vue actuelle."], now, photo="now")

    def force_masked(self, cam: str, now: float, detail: str = "") -> Notice | None:
        """Brain a déjà conclu au masquage (alerte sabotage) : on l'annonce une seule fois et on surveille le retour."""
        st = self.state.setdefault(cam, {"masked": False, "since": None, "masked_at": None})
        if st["masked"]:
            return None                              # déjà annoncée par la surveillance de la vision
        st["masked"], st["since"] = True, None
        return self._masked(cam, st, now, detail)

    @staticmethod
    def _masked(cam: str, st: dict, now: float, detail: str = "") -> Notice:
        st["masked_at"] = now
        lines = [f"La caméra {cam} ne voit plus la scène (objectif couvert ou image noire)."]
        if detail:
            lines.append(detail)
        lines.append("Image jointe : la dernière vue avant le masquage.")
        return Notice("camera_masked", cam, "critical", "Caméra masquée.", "CRITIQUE — Caméra masquée", lines, now,
                      photo="before_mask")

    def is_masked(self, cam: str) -> bool:
        return bool(self.state.get(cam, {}).get("masked"))


def fmt_duration(s: float) -> str:
    s = int(round(s))
    return f"{s // 60} min {s % 60:02d} s" if s >= 60 else f"{s} s"


def route_alert(rules: AlertRules, camera: CameraWatch, a: dict, now: float) -> Notice | None:
    """Une alerte de Brain : le masquage d'une caméra devient « Caméra masquée » (et son retour sera annoncé),
    le reste suit les règles des alertes."""
    device, kind = str(a.get("device_id", "")), str(a.get("type", ""))
    if kind == "sabotage" and device.startswith("cam") and "masqu" in str(a.get("explanation", "")).lower():
        return camera.force_masked(device, now, str(a.get("explanation", "")))
    return rules.on_alert(a, now)
