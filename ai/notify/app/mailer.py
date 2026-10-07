"""Mails d'alerte : texte + HTML, photo intégrée et jointe, envoi SMTP avec file d'attente et nouvel essai.

Configuration (infra/.env) : SMTP_HOST, SMTP_PORT (587 STARTTLS, 465 SSL, 25 ou 1025 sans chiffrement),
SMTP_USER, SMTP_PASSWORD, SMTP_FROM, NOTIFY_TO (adresses séparées par des virgules).
Gmail : SMTP_HOST=smtp.gmail.com, SMTP_PORT=587, SMTP_PASSWORD = mot de passe d'application (pas celui du compte).
"""
from __future__ import annotations

import html
import logging
import queue
import smtplib
import ssl
import threading
import time
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

log = logging.getLogger("notify.mail")


@dataclass
class SmtpConfig:
    host: str = ""
    port: int = 587
    user: str = ""
    password: str = ""
    sender: str = ""
    to: tuple[str, ...] = ()

    @classmethod
    def from_env(cls, env: dict[str, str]) -> SmtpConfig:
        to = tuple(x.strip() for x in env.get("NOTIFY_TO", "").replace(";", ",").split(",") if x.strip())
        user = env.get("SMTP_USER", "").strip()
        return cls(host=env.get("SMTP_HOST", "").strip(), port=int(env.get("SMTP_PORT", "587") or 587), user=user,
                   password=env.get("SMTP_PASSWORD", ""), sender=env.get("SMTP_FROM", "").strip() or user, to=to)

    @property
    def ready(self) -> bool:
        return bool(self.host and self.sender)


def build(subject: str, lines: list[str], when: str, site: str, sender: str, to: list[str],
          photo: bytes | None, photo_label: str = "", stamp: str = "image") -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = f"[Sentinel-X] {subject} — {when}"
    msg["From"], msg["To"], msg["Date"] = sender, ", ".join(to), formatdate(localtime=True)
    text = "\n".join([f"{subject}", f"Date et heure : {when}", f"Site : {site}", "", *lines, "",
                      "Message automatique de Sentinel-X. Détails et acquittement : dashboard (https://192.168.137.1)."])
    msg.set_content(text)
    cid = make_msgid(domain="sentinel-x.local")
    rows = "".join(f"<p style='margin:4px 0'>{html.escape(x)}</p>" for x in lines)
    img = (f"<p style='margin:12px 0 4px;color:#555'>{html.escape(photo_label)}</p>"
           f"<img src='cid:{cid[1:-1]}' style='max-width:640px;border:1px solid #ccc' alt='Image de la caméra'>"
           if photo else "")
    msg.add_alternative(
        f"<div style='font-family:Segoe UI,Arial,sans-serif;font-size:14px'>"
        f"<h2 style='margin:0 0 6px'>{html.escape(subject)}</h2>"
        f"<p style='margin:0 0 10px;color:#555'>{html.escape(when)} · {html.escape(site)}</p>{rows}{img}"
        f"<p style='margin-top:16px;color:#888;font-size:12px'>Message automatique de Sentinel-X.</p></div>",
        subtype="html")
    if photo:
        msg.get_payload()[1].add_related(photo, maintype="image", subtype="jpeg", cid=cid)
        msg.add_attachment(photo, maintype="image", subtype="jpeg",
                           filename=f"sentinel-x-{stamp}.jpg")
    return msg


class Mailer:
    """File d'envoi : un réseau absent (PC sans Internet) ne perd pas l'alerte, elle part au retour du réseau."""

    def __init__(self, cfg: SmtpConfig, max_queue: int = 50) -> None:
        self.cfg = cfg
        self.q: queue.Queue[EmailMessage] = queue.Queue(maxsize=max_queue)
        self.sent: list[EmailMessage] = []
        self.stop = threading.Event()
        threading.Thread(target=self._run, daemon=True, name="mails").start()

    def send(self, msg: EmailMessage) -> None:
        try:
            self.q.put_nowait(msg)
        except queue.Full:
            log.error("file des mails pleine : « %s » abandonné", msg["Subject"])

    def _deliver(self, msg: EmailMessage) -> None:
        c = self.cfg
        if c.port == 465:
            server: smtplib.SMTP = smtplib.SMTP_SSL(c.host, c.port, timeout=20, context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(c.host, c.port, timeout=20)
        with server:
            server.ehlo()
            if c.port == 587:
                server.starttls(context=ssl.create_default_context())
                server.ehlo()
            if c.user and c.password:
                server.login(c.user, c.password)
            server.send_message(msg)

    def _run(self) -> None:
        delay = 5.0
        while not self.stop.is_set():
            msg = self.q.get()
            while not self.stop.is_set():
                try:
                    self._deliver(msg)
                    self.sent.append(msg)
                    log.info("mail envoyé à %s : %s", msg["To"], msg["Subject"])
                    delay = 5.0
                    break
                except smtplib.SMTPAuthenticationError as e:
                    log.error("mail refusé (identifiants SMTP, mot de passe d'application ?) : %s — abandonné", e)
                    break
                except (OSError, smtplib.SMTPException) as e:
                    log.warning("mail non envoyé (%s), nouvel essai dans %.0f s", e, delay)
                    time.sleep(delay)
                    delay = min(300.0, delay * 2)
