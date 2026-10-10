"""Hintergrundaufgaben der Kommunikation (werden von django-q2 zeitgesteuert ausgeführt)."""
import logging

log = logging.getLogger(__name__)


def fetch_cv_mailbox() -> dict:
    from django.conf import settings

    from .mailbox import fetch_mailbox

    if not settings.IMAP_HOST or not settings.IMAP_USER:
        return {"skipped": "IMAP nicht konfiguriert"}  # Zeitplan läuft still weiter, bis die .env ausgefüllt ist

    r = fetch_mailbox()
    log.info("CV-Postfach: %s Mails, %s Anhänge, %s ohne CV", r.messages, r.attachments, r.without_cv)
    return {"messages": r.messages, "attachments": r.attachments, "without_cv": r.without_cv, "skipped": r.skipped}
