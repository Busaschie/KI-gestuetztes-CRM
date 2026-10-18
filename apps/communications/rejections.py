"""Standardabsage (P1 Punkt 7) – nur für Kandidaten mit Auftrag, mit denen Sandra nie gesprochen hat.

Ablauf: täglich (vor dem Briefing) werden fällige Absagen für den nächsten Tag geplant → Telegram-Hinweis mit „Stoppen“
→ Versand über den normalen Ablauf (send_due_messages). Kein KI-Urteil, keine Begründung (Art. 22 DSGVO).
Gestoppte Kandidaten werden nicht erneut automatisch abgesagt. Schalter: STANDARD_REJECTION_ENABLED.
"""
import logging
from datetime import datetime, time, timedelta
from html import escape

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import OutboundMessage

log = logging.getLogger(__name__)

TEMPLATES = {
    "de": (
        "Ihre Bewerbung: {title}",
        "Guten Tag {name},\n\n"
        "vielen Dank für Ihr Interesse an der Position „{title}“ und für Ihre Unterlagen.\n\n"
        "Leider kann ich Ihre Bewerbung für diese Position nicht weiter berücksichtigen.\n\n"
        "Gerne behalte ich Ihre Unterlagen für künftige passende Positionen. Wenn Sie das nicht wünschen, "
        "genügt eine kurze Antwort auf diese E-Mail.\n\n"
        "Für Ihre berufliche Zukunft wünsche ich Ihnen alles Gute.\n\n"
        "Mit freundlichen Grüßen\n{signer}",
    ),
    "en": (
        "Your application: {title}",
        "Dear {name},\n\n"
        "Thank you for your interest in the position “{title}” and for sending your documents.\n\n"
        "Unfortunately, I am unable to consider your application further for this position.\n\n"
        "I would be glad to keep your documents on file for future suitable positions. If you do not wish this, "
        "a short reply to this email is sufficient.\n\n"
        "I wish you all the best for your professional future.\n\n"
        "Kind regards\n{signer}",
    ),
}


def rejection_text(submission) -> tuple[str, str]:
    lang = (submission.candidate.person.preferred_language or "de").lower()[:2]
    subject, body = TEMPLATES.get(lang) or TEMPLATES["en"]  # andere Sprachen (z. B. ro) vorerst Englisch
    values = {"title": submission.mandate.title, "name": str(submission.candidate.person),
              "signer": settings.CONTRACTOR_SIGNER or settings.CONTRACTOR_NAME}
    return subject.format(**values), body.format(**values).rstrip()


def due_submissions(now=None):
    """Kandidaten mit Auftrag, Stufe „Neu“, nie gesprochen, seit STANDARD_REJECTION_DAYS zugeordnet, noch nie abgesagt/gestoppt."""
    from apps.pipeline.models import Submission

    now = now or timezone.now()
    limit = now - timedelta(days=settings.STANDARD_REJECTION_DAYS)
    return (
        Submission.objects.filter(stage=Submission.Stage.NEW, spoken_with=False, created_at__lte=limit)
        .exclude(outbound_messages__kind=OutboundMessage.Kind.STANDARD_REJECTION)
        .select_related("candidate__person", "mandate")
    )


def send_time(now=None) -> datetime:
    """Versandzeitpunkt: nächster Tag um STANDARD_REJECTION_TIME (Ortszeit)."""
    hour, minute = (int(x) for x in settings.STANDARD_REJECTION_TIME.split(":"))
    day = timezone.localtime(now or timezone.now()).date() + timedelta(days=1)
    return timezone.make_aware(datetime.combine(day, time(hour, minute)))


def prepare_standard_rejections(now=None) -> int:
    """Täglich (django-q): fällige Standardabsagen für morgen planen und Sandra mit „Stoppen“-Knopf informieren."""
    from apps.pipeline.models import Submission

    if not settings.STANDARD_REJECTION_ENABLED:
        return 0
    from .services import notify

    now = now or timezone.now()
    when = send_time(now)
    count, skipped = 0, []
    for sub in due_submissions(now):
        person = sub.candidate.person
        if not person.email:
            skipped.append(str(person))
            continue
        subject, body = rejection_text(sub)
        with transaction.atomic():
            msg = OutboundMessage.objects.create(
                kind=OutboundMessage.Kind.STANDARD_REJECTION, status=OutboundMessage.Status.SCHEDULED,
                recipient=person, mandate=sub.mandate, subject=subject, body=body,
                is_automatic=True, approved_at=now, scheduled_for=when,
            )
            msg.submissions.set([sub])
            sub.stage = Submission.Stage.REJECTION_PREPARED
            sub.save(update_fields=["stage", "updated_at"])
        notify(
            f"✉️ <b>Standardabsage morgen {timezone.localtime(when):%d.%m. %H:%M}</b>\n"
            f"{escape(str(person))} → {escape(str(sub.mandate))}",
            [[("⛔ Stoppen", f"o{msg.pk}:stop")]],
        )
        count += 1
    if skipped:
        notify("⚠️ Standardabsage nicht möglich (keine E-Mail-Adresse): " + escape(", ".join(skipped)))
    return count


def check_still_due(msg) -> None:
    """Vor dem Versand: hat Sandra den Kandidaten inzwischen anders markiert, geht die Absage nicht raus."""
    from apps.pipeline.models import Submission

    from .services import MessageObsolete

    ok = (Submission.Stage.NEW, Submission.Stage.REJECTION_PREPARED)
    for sub in msg.submissions.select_related("candidate__person"):
        if sub.spoken_with or sub.stage not in ok:
            raise MessageObsolete(
                f"{sub.candidate.person}: Stufe „{sub.get_stage_display()}“"
                + (", persönlich gesprochen" if sub.spoken_with else "") + " – Standardabsage entfällt."
            )


def reset_after_stop(msg) -> None:
    """Gestoppt → Kandidat zurück auf „Neu“ (wird wegen der gestoppten Nachricht nicht erneut abgesagt)."""
    from apps.pipeline.models import Submission

    msg.submissions.filter(stage=Submission.Stage.REJECTION_PREPARED).update(
        stage=Submission.Stage.NEW, updated_at=timezone.now())


def mark_rejected(msg, now) -> None:
    from apps.pipeline.models import Submission

    msg.submissions.update(stage=Submission.Stage.REJECTED, last_feedback_at=now, updated_at=now)


def upcoming_rejections():
    """Für das Briefing: geplante Standardabsagen."""
    return list(
        OutboundMessage.objects.filter(kind=OutboundMessage.Kind.STANDARD_REJECTION, status=OutboundMessage.Status.SCHEDULED)
        .select_related("recipient", "mandate").order_by("scheduled_for")
    )
