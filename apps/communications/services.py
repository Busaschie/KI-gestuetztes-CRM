"""Geschäftslogik – Views bleiben schlank.

Profil/CV/Shortlist an Kunden (P1 Punkt 4): Entwurf → Freigabe mit Stopp-Fenster → Versand per E-Mail (SMTP, Versand-Postfach).
Die harte Vertragssperre sitzt in OutboundMessage.save(); hier kommen Zustimmung, Empfänger und Anhänge dazu.
Später (vermerkt): statt Original-CV ein eigenes Kandidatenprofil als PDF in Sandras Design (OutboundAttachment.file).
"""
import logging
import mimetypes
from datetime import timedelta
from html import escape

from django.conf import settings
from django.core.mail import EmailMessage
from django.db import transaction
from django.utils import timezone

from .models import OutboundAttachment, OutboundMessage

log = logging.getLogger(__name__)


class MessageError(Exception):
    """Nachricht kann (noch) nicht versendet werden – Text ist für Sandra lesbar."""


class MessageObsolete(MessageError):
    """Nachricht ist überholt (z. B. Standardabsage, aber Sandra hat den Kandidaten inzwischen anders markiert)."""


def notify(text: str, buttons=None) -> None:
    from apps.clients.services import notify as _notify  # ein gemeinsamer Telegram-Hinweis
    _notify(text, buttons)


# --- Entwurf ------------------------------------------------------------------------------------

def _candidate_line(sub) -> str:
    line = f"- {sub.candidate.person}"
    return f"{line}, {sub.candidate.headline}" if sub.candidate.headline else line


def profile_text(mandate, submissions) -> tuple[str, str]:
    """Betreff und Text aus der Vorlage – Sandra kann beides vor der Freigabe ändern."""
    many = len(submissions) > 1
    subject = f"{'Kandidatenvorschläge' if many else 'Kandidatenvorschlag'}: {mandate.title}"
    contact = mandate.contact_person
    greeting = f"Guten Tag {contact}" if contact else "Guten Tag"
    intro = (f"anbei erhalten Sie die Lebensläufe folgender Kandidaten für die Position „{mandate.title}“:"
             if many else f"anbei erhalten Sie den Lebenslauf des folgenden Kandidaten für die Position „{mandate.title}“:")
    lines = "\n".join(_candidate_line(s) for s in submissions)
    signer = settings.CONTRACTOR_SIGNER or settings.CONTRACTOR_NAME
    body = (f"{greeting},\n\n{intro}\n\n{lines}\n\n"
            "Gerne bespreche ich die Profile mit Ihnen und stimme die nächsten Schritte ab.\n\n"
            f"Mit freundlichen Grüßen\n{signer}").rstrip()
    return subject, body


def _current_cv(submission):
    return submission.candidate.cvs.filter(is_current=True).order_by("-received_at").first() \
        or submission.candidate.cvs.order_by("-received_at").first()


def prepare_profile_message(submissions) -> OutboundMessage:
    """Entwurf „Profil an Kunden“ für einen oder mehrere Kandidaten desselben Auftrags (Shortlist = eine Mail)."""
    submissions = list(submissions)
    if not submissions:
        raise MessageError("Keine Kandidaten ausgewählt.")
    mandates = {s.mandate_id for s in submissions}
    if len(mandates) > 1:
        raise MessageError("Bitte nur Kandidaten desselben Auftrags auswählen (eine Mail je Auftrag).")
    mandate = submissions[0].mandate
    if not mandate.contact_person:
        raise MessageError(f"Der Auftrag „{mandate}“ hat keinen Ansprechpartner (Empfänger).")
    subject, body = profile_text(mandate, submissions)
    with transaction.atomic():
        msg = OutboundMessage.objects.create(
            kind=OutboundMessage.Kind.PROFILE_TO_CLIENT, status=OutboundMessage.Status.DRAFT,
            recipient=mandate.contact_person, mandate=mandate, subject=subject, body=body,
        )
        msg.submissions.set(submissions)
        for sub in submissions:
            if cv := _current_cv(sub):
                OutboundAttachment.objects.create(message=msg, cv=cv, filename=cv.original_filename)
    return msg


# --- Prüfung, Freigabe, Stopp -------------------------------------------------------------------

def check_sendable(msg: OutboundMessage) -> None:
    """Alle Bedingungen vor dem Versand – Fehler als lesbarer Text."""
    if not msg.recipient.email:
        raise MessageError(f"Empfänger {msg.recipient} hat keine E-Mail-Adresse.")
    if not settings.DEFAULT_FROM_EMAIL:
        raise MessageError("Absender fehlt (DEFAULT_FROM_EMAIL in der .env).")
    if msg.kind == OutboundMessage.Kind.PROFILE_TO_CLIENT:
        if not msg.mandate_id or not msg.mandate.has_signed_contract:
            raise MessageError("Gesperrt: Für diesen Auftrag gibt es keinen unterschriebenen Vertrag.")
        subs = list(msg.submissions.select_related("candidate__person"))
        if not subs:
            raise MessageError("Keine Kandidaten an der Nachricht.")
        if missing := [str(s.candidate.person) for s in subs if not s.consent_to_present_at]:
            raise MessageError("Keine dokumentierte Zustimmung zur Vorstellung: " + ", ".join(missing))
        with_cv = {a.cv.profile_id for a in msg.attachments.select_related("cv") if a.cv_id}
        if missing := [str(s.candidate.person) for s in subs if s.candidate_id not in with_cv]:
            raise MessageError("Kein Lebenslauf im Anhang für: " + ", ".join(missing))
    if msg.kind == OutboundMessage.Kind.STANDARD_REJECTION:
        from .rejections import check_still_due
        check_still_due(msg)


def schedule_message(msg: OutboundMessage, user=None) -> OutboundMessage:
    """Freigeben: nach OUTBOUND_STOP_MINUTES geht die Mail raus, bis dahin kann Sandra stoppen."""
    if msg.status not in (OutboundMessage.Status.DRAFT, OutboundMessage.Status.STOPPED, OutboundMessage.Status.FAILED):
        raise MessageError(f"Nur Entwürfe können freigegeben werden (Status: {msg.get_status_display()}).")
    check_sendable(msg)
    msg.approved_at = timezone.now()
    minutes = settings.OUTBOUND_STOP_MINUTES
    if minutes <= 0:
        msg.save(update_fields=["approved_at", "updated_at"])
        return send_message(msg)
    msg.status = OutboundMessage.Status.SCHEDULED
    msg.scheduled_for = timezone.now() + timedelta(minutes=minutes)
    msg.error = ""
    msg.save(update_fields=["status", "scheduled_for", "approved_at", "error", "updated_at"])
    when = timezone.localtime(msg.scheduled_for)
    names = ", ".join(str(s.candidate.person) for s in msg.submissions.select_related("candidate__person"))
    notify(
        f"✉️ <b>{escape(msg.get_kind_display())} geht um {when:%H:%M} raus</b>\n{escape(str(msg.mandate or ''))}\n"
        f"An: {escape(str(msg.recipient))} &lt;{escape(msg.recipient.email)}&gt;\n"
        + (f"Kandidaten: {escape(names)}\n" if names else "") + f"Anhänge: {msg.attachments.count()}",
        [[("⛔ Stoppen", f"o{msg.pk}:stop"), ("📤 Jetzt senden", f"o{msg.pk}:now")]],
    )
    return msg


def send_now(msg: OutboundMessage) -> OutboundMessage:
    """Freigeben und ohne Stopp-Fenster senden (Admin-Aktion „Sofort senden“)."""
    check_sendable(msg)
    if not msg.approved_at:
        msg.approved_at = timezone.now()
        msg.save(update_fields=["approved_at", "updated_at"])
    return send_message(msg)


def stop_message(msg: OutboundMessage) -> OutboundMessage:
    if msg.status != OutboundMessage.Status.SCHEDULED:
        raise MessageError(f"Nur geplante Nachrichten können gestoppt werden (Status: {msg.get_status_display()}).")
    msg.status, msg.scheduled_for = OutboundMessage.Status.STOPPED, None
    msg.save(update_fields=["status", "scheduled_for", "updated_at"])
    if msg.kind == OutboundMessage.Kind.STANDARD_REJECTION:
        from .rejections import reset_after_stop
        reset_after_stop(msg)
    return msg


# --- Versand ------------------------------------------------------------------------------------

def _build_email(msg: OutboundMessage) -> EmailMessage:
    email = EmailMessage(
        subject=msg.subject, body=msg.body, from_email=settings.DEFAULT_FROM_EMAIL,
        to=[msg.recipient.email], reply_to=settings.EMAIL_REPLY_TO or None,
    )
    for att in msg.attachments.select_related("cv"):
        source = att.source()
        if not source:
            continue
        with source.open("rb") as fh:
            data = fh.read()
        name = att.filename or source.name.rsplit("/", 1)[-1]
        email.attach(name, data, mimetypes.guess_type(name)[0] or "application/octet-stream")
    return email


def send_message(msg: OutboundMessage) -> OutboundMessage:
    """Sofortiger Versand (nach Ablauf des Stopp-Fensters oder per „Jetzt senden“)."""
    if msg.status not in (OutboundMessage.Status.DRAFT, OutboundMessage.Status.SCHEDULED,
                          OutboundMessage.Status.STOPPED, OutboundMessage.Status.FAILED):
        raise MessageError(f"Nachricht kann nicht gesendet werden (Status: {msg.get_status_display()}).")
    if not msg.approved_at:
        raise MessageError("Nachricht ist nicht freigegeben.")
    check_sendable(msg)
    try:
        _build_email(msg).send(fail_silently=False)
    except Exception as e:  # noqa: BLE001 – SMTP-/Dateifehler protokollieren, nicht verschlucken
        msg.status, msg.scheduled_for, msg.error = OutboundMessage.Status.FAILED, None, str(e)
        msg.save(update_fields=["status", "scheduled_for", "error", "updated_at"])
        raise MessageError(f"Versand fehlgeschlagen: {e}") from e

    now = timezone.now()
    with transaction.atomic():
        msg.status, msg.sent_at, msg.scheduled_for, msg.error = OutboundMessage.Status.SENT, now, None, ""
        msg.save(update_fields=["status", "sent_at", "scheduled_for", "error", "updated_at"])
        from .models import mark_contacted
        mark_contacted(msg.recipient_id, now)
        if msg.kind == OutboundMessage.Kind.PROFILE_TO_CLIENT:
            _mark_presented(msg, now)
        elif msg.kind == OutboundMessage.Kind.STANDARD_REJECTION:
            from .rejections import mark_rejected
            mark_rejected(msg, now)
    return msg


def _mark_presented(msg: OutboundMessage, now) -> None:
    from apps.pipeline.models import Submission

    early = (Submission.Stage.NEW, Submission.Stage.IN_TALKS, Submission.Stage.ON_HOLD)
    for sub in msg.submissions.all():
        sub.presented_at = sub.presented_at or now
        if sub.stage in early:
            sub.stage = Submission.Stage.PRESENTED
        sub.save(update_fields=["presented_at", "stage", "updated_at"])


def send_due_messages() -> int:
    """Läuft jede Minute (django-q): freigegebene Nachrichten senden, deren Stopp-Fenster abgelaufen ist."""
    due = OutboundMessage.objects.filter(status=OutboundMessage.Status.SCHEDULED, scheduled_for__lte=timezone.now())
    sent = 0
    for msg in due.select_related("recipient", "mandate"):
        try:
            send_message(msg)
            sent += 1
            notify(f"📤 {escape(msg.get_kind_display())} versendet an {escape(str(msg.recipient))}: {escape(msg.subject)}")
        except MessageObsolete as e:  # z. B. Sandra hat den Kandidaten inzwischen anders markiert – still stoppen
            msg.status, msg.scheduled_for, msg.error = OutboundMessage.Status.STOPPED, None, str(e)
            msg.save(update_fields=["status", "scheduled_for", "error", "updated_at"])
            notify(f"ℹ️ Nicht versendet (überholt): {escape(msg.subject)}\n{escape(str(e))}")
        except MessageError as e:
            if msg.status == OutboundMessage.Status.SCHEDULED:  # Prüfung fehlgeschlagen → zurück auf Entwurf
                msg.status, msg.scheduled_for, msg.error = OutboundMessage.Status.DRAFT, None, str(e)
                msg.save(update_fields=["status", "scheduled_for", "error", "updated_at"])
            notify(f"⚠️ <b>Nicht</b> versendet: {escape(msg.subject)}\n{escape(str(e))}\nBitte im Admin prüfen.")
    return sent
