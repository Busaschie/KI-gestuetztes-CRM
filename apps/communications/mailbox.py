"""Abruf des CV-Postfachs per IMAP (P1 Punkt 1).

Sicherheitsregeln:
- Es wird nichts gelöscht. Verarbeitete Mails werden nur als gelesen markiert
  (optional in einen Ordner verschoben, falls IMAP_PROCESSED_FOLDER gesetzt ist).
- Jede Mail wird nur einmal verarbeitet (Message-ID in InboundItem.external_id).
- Mails ohne CV-Anhang landen als "Nicht zugeordnet" mit Betreff und Text – z. B. Jobbörsen,
  die nur einen Link aufs Portal schicken.
"""
import email
import imaplib
import logging
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.policy import default as default_policy
from pathlib import PurePath

from django.conf import settings
from django.utils import timezone

from .models import InboundItem

log = logging.getLogger(__name__)
CV_SUFFIXES = {".pdf", ".docx", ".doc"}
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024
IMAP_TIMEOUT = 30  # Sekunden – sonst hängt der Abruf bei falschem Server/Port endlos


@dataclass
class FetchResult:
    messages: int = 0
    attachments: int = 0
    without_cv: int = 0
    skipped: int = 0
    inbound_ids: list = field(default_factory=list)


def connect() -> imaplib.IMAP4:
    if not settings.IMAP_HOST or not settings.IMAP_USER:
        raise RuntimeError("IMAP_HOST und IMAP_USER fehlen in der .env")
    cls = imaplib.IMAP4_SSL if settings.IMAP_SSL else imaplib.IMAP4
    try:
        conn = cls(settings.IMAP_HOST, settings.IMAP_PORT, timeout=IMAP_TIMEOUT)
        conn.login(settings.IMAP_USER, settings.IMAP_PASSWORD)
    except (OSError, imaplib.IMAP4.error) as e:
        raise RuntimeError(
            f"IMAP-Verbindung zu {settings.IMAP_HOST}:{settings.IMAP_PORT} fehlgeschlagen: {e} – "
            "Server, Port, SSL, Benutzer und Passwort in der .env prüfen"
        ) from e
    return conn


def fetch_mailbox(conn: imaplib.IMAP4 | None = None, enqueue=None, log_line=lambda msg: None) -> FetchResult:
    """Holt ungelesene Mails, legt pro CV-Anhang einen Eingang an und stößt die Auslese an."""
    from agents.tasks import enqueue_agent
    from apps.candidates.services import create_inbound_from_file

    enqueue = enqueue or (lambda item: enqueue_agent("cv_parser", inbound_id=item.pk, origin="email"))
    own_conn = conn is None
    if own_conn:
        log_line(f"Verbinde mit {settings.IMAP_HOST}:{settings.IMAP_PORT} …")
    conn = conn or connect()
    result = FetchResult()
    try:
        conn.select(settings.IMAP_FOLDER)
        typ, data = conn.uid("SEARCH", None, "UNSEEN")
        uids = data[0].split() if typ == "OK" and data and data[0] else []
        log_line(f"Verbunden – {len(uids)} ungelesene Mail(s) in {settings.IMAP_FOLDER}")
        for uid in uids:
            typ, msg_data = conn.uid("FETCH", uid, "(BODY.PEEK[])")  # PEEK: noch nicht als gelesen markieren
            if typ != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
                log.warning("Mail %s konnte nicht gelesen werden", uid)
                continue
            msg = email.message_from_bytes(msg_data[0][1], policy=default_policy)
            result.messages += 1
            message_id = (msg.get("Message-ID") or f"uid-{uid.decode()}").strip()
            if InboundItem.objects.filter(external_id__startswith=message_id).exists():
                result.skipped += 1
                _mark_done(conn, uid)
                continue

            sender = str(msg.get("From", ""))[:255]
            subject = str(msg.get("Subject", ""))[:255]
            attachments = list(_cv_attachments(msg))
            if not attachments:
                InboundItem.objects.create(
                    channel=InboundItem.Channel.EMAIL, status=InboundItem.Status.UNASSIGNED,
                    external_id=message_id[:255], subject=subject, sender=sender, context=subject,
                    raw_text=_body_text(msg)[:5000], processed_at=timezone.now(),
                    error="E-Mail ohne CV-Anhang – evtl. Link aufs Jobportal, bitte prüfen",
                )
                result.without_cv += 1
            log_line(f"Mail „{subject}“ von {sender}: {len(attachments)} CV-Anhang/Anhänge")
            for n, (filename, payload) in enumerate(attachments, start=1):
                item = create_inbound_from_file(filename, payload, channel=InboundItem.Channel.EMAIL)
                item.external_id = f"{message_id}#{n}"[:255]
                item.sender, item.context = sender, subject
                item.save(update_fields=["external_id", "sender", "context", "updated_at"])
                enqueue(item)
                result.attachments += 1
                result.inbound_ids.append(item.pk)
            _mark_done(conn, uid)
    finally:
        if own_conn:
            try:
                conn.logout()
            except Exception:  # noqa: BLE001
                pass
    return result


def _cv_attachments(msg: EmailMessage):
    for part in msg.iter_attachments():
        filename = part.get_filename()
        if not filename:
            continue
        filename = PurePath(filename.replace("\\", "/")).name  # keine Pfadangaben aus der Mail übernehmen
        if PurePath(filename).suffix.lower() not in CV_SUFFIXES:
            continue
        payload = part.get_payload(decode=True) or b""
        if 0 < len(payload) <= MAX_ATTACHMENT_BYTES:
            yield filename, payload


def _body_text(msg: EmailMessage) -> str:
    body = msg.get_body(preferencelist=("plain", "html"))
    return body.get_content() if body else ""


def _mark_done(conn, uid):
    folder = settings.IMAP_PROCESSED_FOLDER
    if folder:
        typ, _ = conn.uid("MOVE", uid, folder)
        if typ == "OK":
            return
        log.warning("Verschieben nach %s nicht möglich – Mail wird nur als gelesen markiert", folder)
    conn.uid("STORE", uid, "+FLAGS", "(\\Seen)")
