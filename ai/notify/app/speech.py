"""Annonces vocales sur les haut-parleurs du PC serveur, hors ligne.

Windows : synthèse vocale intégrée (System.Speech, voix française si elle est installée), précédée d'un bip.
Linux / Raspberry Pi : espeak-ng s'il est installé. Sinon, l'annonce est seulement écrite dans le journal.
Les annonces passent par une file : le service ne se bloque jamais pendant qu'une phrase est dite.
"""
from __future__ import annotations

import logging
import queue
import shutil
import subprocess
import sys
import threading

log = logging.getLogger("notify.voix")

PS_SPEAK = (
    "Add-Type -AssemblyName System.Speech; "
    "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
    "$v = $s.GetInstalledVoices() | Where-Object {{ $_.Enabled -and $_.VoiceInfo.Culture.Name -like 'fr*' }} "
    "| Select-Object -First 1; if ($v) {{ $s.SelectVoice($v.VoiceInfo.Name) }}; "
    "$s.Volume = 100; $s.Rate = 0; "
    "[console]::beep(880, 220); [console]::beep(660, 260); "
    "for ($i = 0; $i -lt {repeat}; $i++) {{ $s.Speak('{text}') }}"
)


def command(text: str, repeat: int = 1, platform: str | None = None) -> list[str] | None:
    """Commande système qui dit le texte, ou None si aucune voix n'est disponible."""
    platform = platform or sys.platform
    if platform.startswith("win"):
        safe = text.replace("'", "''")            # chaîne PowerShell entre apostrophes
        return ["powershell", "-NoProfile", "-NonInteractive", "-Command", PS_SPEAK.format(text=safe, repeat=repeat)]
    for exe in ("espeak-ng", "espeak"):
        if shutil.which(exe):
            return [exe, "-v", "fr", " ".join([text] * repeat)]
    return None


class Speaker:
    def __init__(self, enabled: bool = True, repeat: int = 2) -> None:
        self.enabled, self.repeat = enabled, repeat
        self.q: queue.Queue[str] = queue.Queue(maxsize=20)
        self.spoken: list[str] = []                 # historique (tests, journal)
        threading.Thread(target=self._run, daemon=True, name="voix").start()

    def say(self, text: str) -> None:
        if not self.enabled:
            return
        try:
            self.q.put_nowait(text)
        except queue.Full:
            log.warning("file des annonces pleine : « %s » ignorée", text)

    def _run(self) -> None:
        while True:
            text = self.q.get()
            self.spoken.append(text)
            cmd = command(text, self.repeat)
            log.info("ANNONCE : %s", text)
            if cmd is None:
                continue
            try:
                subprocess.run(cmd, timeout=30, check=False, capture_output=True)
            except (OSError, subprocess.TimeoutExpired) as e:
                log.warning("synthèse vocale indisponible (%s) : « %s »", e, text)
