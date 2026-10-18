"""Tägliches Briefing: fällige Wiedervorlagen, nicht Zugeordnetes, offene Verträge."""
import logging
from datetime import timedelta
from html import escape

from django.conf import settings
from django.utils import timezone

from apps.clients.models import Contract
from apps.communications.models import FollowUp, InboundItem
from apps.jobs.models import Mandate

log = logging.getLogger(__name__)

MAX_ITEMS = 10
OPEN_INBOUND = (InboundItem.Status.UNASSIGNED, InboundItem.Status.NEEDS_QUESTION, InboundItem.Status.FAILED)
CONTRACT_WAITING_DAYS = 3


def _lines(items, fmt) -> list[str]:
    out = [fmt(i) for i in items[:MAX_ITEMS]]
    if len(items) > MAX_ITEMS:
        out.append(f"… und {len(items) - MAX_ITEMS} weitere")
    return out


def build_briefing(today=None) -> str:
    today = today or timezone.localdate()
    parts = [f"<b>Briefing {today:%d.%m.%Y}</b>"]

    from apps.communications.contact_care import CARE_REASONS, suggestions

    follow_ups = list(  # Kontaktpflege-Vorschläge kommen gesondert (höchstens N pro Tag)
        FollowUp.objects.filter(done_at__isnull=True, due_date__lte=today).exclude(reason__in=CARE_REASONS)
        .select_related("person", "mandate")
    )
    if follow_ups:
        def fmt_fu(f):
            late = " ⚠️" if f.due_date < today else ""
            who = f" – {escape(str(f.person))}" if f.person else ""
            return f"• {f.due_date:%d.%m.}{late} {escape(f.text)}{who}"
        parts += ["", f"<b>Wiedervorlagen ({len(follow_ups)})</b>", *_lines(follow_ups, fmt_fu)]

    inbound = list(InboundItem.objects.filter(status__in=OPEN_INBOUND).order_by("created_at"))
    if inbound:
        def fmt_in(i):
            label = escape(i.subject or i.raw_text[:60] or "(ohne Text)")
            return f"• {i.get_channel_display()}, {timezone.localtime(i.created_at):%d.%m.}: {label} ({i.get_status_display()})"
        parts += ["", f"<b>Nicht zugeordnet ({len(inbound)})</b>", *_lines(inbound, fmt_in)]

    limit = timezone.now() - timedelta(days=CONTRACT_WAITING_DAYS)
    contracts = list(
        Contract.objects.filter(status__in=[Contract.Status.SENT, Contract.Status.PENDING], sent_at__lte=limit)
        .select_related("mandate", "company")
    )
    if contracts:
        def fmt_c(c):
            rem = f", {c.reminders_sent} Erinnerung(en)" if c.reminders_sent else ""
            return f"• {escape(str(c.mandate))} – versendet {timezone.localtime(c.sent_at):%d.%m.}{rem}"
        parts += ["", f"<b>Verträge ohne Unterschrift ({len(contracts)})</b>", *_lines(contracts, fmt_c)]

    # Aufträge, die laufen, aber noch gar keinen Vertrag auf dem Weg haben (Versand am System vorbei möglich)
    on_the_way = [Contract.Status.SCHEDULED, Contract.Status.SENT, Contract.Status.PENDING, *Contract.SIGNED_STATES]
    no_contract = list(
        Mandate.objects.filter(status=Mandate.Status.ACTIVE).exclude(contracts__status__in=on_the_way)
        .select_related("company").distinct()
    )
    if no_contract:
        parts += ["", f"<b>Aktive Aufträge ohne Vertrag ({len(no_contract)})</b>",
                  *_lines(no_contract, lambda m: f"• {escape(str(m))}")]

    care = suggestions(today).count()
    if care:
        shown = min(care, settings.CONTACT_SUGGESTIONS_PER_DAY)
        parts += ["", f"<b>Kontaktvorschläge ({shown} von {care})</b> – einzeln unten mit Knöpfen"]

    from apps.communications.rejections import upcoming_rejections

    rejections = upcoming_rejections()
    if rejections:
        def fmt_r(m):
            return (f"• {timezone.localtime(m.scheduled_for):%d.%m. %H:%M} {escape(str(m.recipient))}"
                    f" → {escape(str(m.mandate or ''))}")
        parts += ["", f"<b>Geplante Standardabsagen ({len(rejections)})</b> – Stopp über die Einzelnachricht oder im Admin",
                  *_lines(rejections, fmt_r)]

    if len(parts) == 1:
        parts += ["", "Heute nichts Dringendes. 👍"]
    return "\n".join(parts)


def send_daily_briefing() -> int:
    """Wird von django-q täglich aufgerufen. Gibt die Zahl der Empfänger zurück."""
    from .telegram import TelegramClient

    chat_ids = settings.TELEGRAM_ALLOWED_CHAT_IDS
    if not chat_ids:
        log.warning("Briefing nicht gesendet: TELEGRAM_ALLOWED_CHAT_IDS ist leer")
        return 0
    client = TelegramClient()
    for chat_id in chat_ids:
        send_briefing(chat_id, client)
    return len(chat_ids)


def send_briefing(chat_id: int, client) -> None:
    """Briefing-Text, danach die Kontaktvorschläge des Tages einzeln mit Knöpfen."""
    from apps.communications.contact_care import suggestions

    from .followups import render_suggestion

    client.send_message(chat_id, build_briefing())
    for fu in suggestions()[:settings.CONTACT_SUGGESTIONS_PER_DAY]:
        client.send_message(chat_id, *render_suggestion(fu))
