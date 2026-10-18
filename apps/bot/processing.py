"""Nachricht → Transkript → Vorschlag (Notiz, Person, Wiedervorlage) → Bestätigung per Knopf → Speichern.

Nichts wird ohne Bestätigung in Notizen/Wiedervorlagen übernommen. Der Eingang (InboundItem) mit
Transkript bleibt immer erhalten.
"""
import logging
import time
from datetime import date, timedelta
from html import escape

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from agents.llm.base import LLMError
from agents.llm.transcribe import get_transcriber, name_hints
from apps.communications.models import FollowUp, InboundItem, Note
from apps.contacts.models import Person
from apps.core.models import Origin

from .extract import extract_note, find_persons, person_label
from .models import BotDraft
from .telegram import TelegramError

log = logging.getLogger(__name__)


def remember_message(draft: BotDraft, sent) -> None:
    """IDs der Bot-Meldungen zu einem Vorschlag merken – zum Löschen beim Verwerfen."""
    if sent and sent.get("message_id"):
        draft.data = {**(draft.data or {}), "_tg": [*(draft.data or {}).get("_tg", []), sent["message_id"]]}
        draft.save(update_fields=["data", "updated_at"])


def get_client():
    from .telegram import TelegramClient
    return TelegramClient()


def process_draft(draft_id: int, client=None) -> BotDraft:
    """Transkribieren (bei Sprache), auslesen, Personen suchen, Vorschlag mit Knöpfen senden."""
    client = client or get_client()
    draft = BotDraft.objects.select_related("inbound").get(pk=draft_id)
    item = draft.inbound
    try:
        if item.channel == InboundItem.Channel.VOICE and not item.raw_text:
            with item.attachment.open("rb") as f:
                audio = f.read()
            t0 = time.monotonic()
            log.info("Vorschlag #%s: Transkription startet", draft.pk)
            item.raw_text = get_transcriber().transcribe(audio, item.attachment.name.rsplit("/", 1)[-1], name_hints())
            item.subject = item.raw_text[:80]
            item.save(update_fields=["raw_text", "subject", "updated_at"])
            log.info("Vorschlag #%s: Transkription fertig (%.0f s)", draft.pk, time.monotonic() - t0)
            if not item.raw_text:
                raise LLMError("Keine Sprache erkannt")
            remember_message(draft, client.send_message(draft.chat_id, f"🎙 <i>{escape(item.raw_text[:600])}</i>\n⏳ Werte aus …"))
        t0 = time.monotonic()
        draft.data = {**extract_note(item.raw_text), "_tg": (draft.data or {}).get("_tg", [])}
        log.info("Vorschlag #%s: Auswertung fertig (%.0f s)", draft.pk, time.monotonic() - t0)
    except LLMError as e:
        _fail(draft, item, str(e), client)
        return draft
    except Exception as e:  # unerwarteter Fehler: nicht „In Verarbeitung“ hängen lassen
        log.exception("Vorschlag #%s: unerwarteter Fehler", draft.pk)
        _fail(draft, item, f"Interner Fehler ({type(e).__name__}: {e})", client)
        return draft

    if draft.data.get("intent") == "mandate":  # neuer Auftrag (P1 Punkt 4)
        from .mandates import prepare
        prepare(draft)
    elif draft.data.get("intent") == "assign":  # Kandidat einem Auftrag zuordnen
        from .assign import prepare as prepare_assign
        prepare_assign(draft)
    else:
        persons = find_persons(draft.data.get("person_name"), draft.data.get("company"))
        draft.candidates = [p.pk for p in persons]
        draft.person = persons[0] if len(persons) == 1 else None
        draft.status = BotDraft.Status.AWAITING
        draft.save()
    try:
        _show(draft, client, new=True)
    except TelegramError as e:
        log.warning("Vorschlag #%s nicht gesendet (%s) – über /offen abrufbar", draft.pk, e)
    return draft


def _fail(draft, item, error, client):
    draft.status = BotDraft.Status.FAILED
    draft.save(update_fields=["status", "updated_at"])
    item.status, item.error, item.processed_at = InboundItem.Status.FAILED, error[:2000], timezone.now()
    item.save(update_fields=["status", "error", "processed_at", "updated_at"])
    hint = f"\n\nTranskript: <i>{escape(item.raw_text[:500])}</i>" if item.raw_text else ""
    remember_message(draft, _safe_send(
        client, draft.chat_id,
        f"⚠️ Konnte die Nachricht nicht verarbeiten: {escape(error[:300])}\n"
        f"Gespeichert als Eingang #{item.pk}.{hint}",
        [[("🔄 Erneut versuchen", f"d{draft.pk}:retry"), ("🗑 Verwerfen + löschen", f"d{draft.pk}:x")]]))


def _safe_send(client, chat_id, text, buttons=None):
    """Senden darf die Verarbeitung nicht abbrechen – Vorschläge bleiben über /offen erreichbar."""
    try:
        return client.send_message(chat_id, text, buttons)
    except TelegramError as e:
        log.warning("Telegram-Nachricht nicht gesendet: %s", e)
        return None


def recover_stuck(client, older_than_minutes: int | None = None) -> int:
    """Vorschläge, die bei einem Absturz/Neustart in „In Verarbeitung“ hängen geblieben sind → Fehler + Retry-Knopf.
    Ohne qcluster (TELEGRAM_ASYNC=False) ist beim Start jeder davon hängen geblieben; mit qcluster nur ältere."""
    if older_than_minutes is None:
        older_than_minutes = 30 if settings.TELEGRAM_ASYNC else 0
    limit = timezone.now() - timedelta(minutes=older_than_minutes)
    stuck = BotDraft.objects.filter(status=BotDraft.Status.PROCESSING, updated_at__lte=limit).select_related("inbound")
    count = 0
    for draft in stuck:
        _fail(draft, draft.inbound, "Verarbeitung wurde unterbrochen (Neustart)", client)
        count += 1
    return count


# --- Anzeige ---------------------------------------------------------------------------------------

def render(draft: BotDraft) -> tuple[str, list]:
    if draft.data.get("intent") == "mandate" and "m" in draft.data:
        from .mandates import render as render_mandate
        return render_mandate(draft)
    if draft.data.get("intent") == "assign" and "a" in draft.data:
        from .assign import render as render_assign
        return render_assign(draft)
    d = draft.data
    lines = [f"📝 <b>Notiz:</b> {escape(d.get('note', ''))}"]
    if draft.person:
        lines.append(f"👤 <b>Person:</b> {escape(person_label(draft.person))}")
    elif draft.candidates:
        lines.append(f"👤 <b>Person:</b> „{escape(d.get('person_name') or '')}“ – mehrere Treffer, bitte wählen:")
    elif d.get("person_name"):
        lines.append(f"👤 <b>Person:</b> „{escape(d['person_name'])}“ – nicht in der Datenbank gefunden")
    else:
        lines.append("👤 <b>Person:</b> keine genannt")
    if d.get("follow_up_date"):
        due = date.fromisoformat(d["follow_up_date"])
        lines.append(f"📅 <b>Wiedervorlage:</b> {due:%d.%m.%Y} – {escape(d.get('follow_up_text') or '')}")

    key = f"d{draft.pk}"
    buttons = []
    if draft.person:
        buttons.append([("✅ Speichern", f"{key}:ok")])
    elif draft.candidates:
        by_id = {p.pk: p for p in Person.objects.filter(pk__in=draft.candidates).prefetch_related("employments__company")}
        buttons += [[(f"👤 {person_label(by_id[i])}"[:60], f"{key}:p{i}")] for i in draft.candidates if i in by_id]
    if d.get("follow_up_date"):
        buttons.append([("📅 +1 Tag", f"{key}:f1"), ("📅 +1 Woche", f"{key}:f7"), ("🚫 Keine WV", f"{key}:f0")])
    else:
        buttons.append([("📅 WV morgen", f"{key}:f1"), ("📅 WV in 1 Woche", f"{key}:f7")])
    buttons.append([("💾 Ohne Person", f"{key}:np"), ("🗑 Verwerfen + löschen", f"{key}:x")])
    return "\n".join(lines), buttons


def shift_follow_up(draft: BotDraft, days: int) -> None:
    """days=0: Wiedervorlage entfernen; sonst ab bisherigem Datum (bzw. heute) verschieben."""
    d = draft.data
    if days == 0:
        d["follow_up_date"], d["follow_up_text"] = None, None
    else:
        base = date.fromisoformat(d["follow_up_date"]) if d.get("follow_up_date") else timezone.localdate()
        d["follow_up_date"] = (base + timedelta(days=days)).isoformat()
        d["follow_up_text"] = d.get("follow_up_text") or (d.get("note") or "")[:255]
    draft.data = d
    draft.save(update_fields=["data", "updated_at"])


def _show(draft, client, new=False):
    text, buttons = render(draft)
    if new or not draft.message_id:
        msg = client.send_message(draft.chat_id, text, buttons)
        draft.message_id = (msg or {}).get("message_id")
        draft.save(update_fields=["message_id", "updated_at"])
    else:
        client.edit_message(draft.chat_id, draft.message_id, text, buttons)


# --- Knöpfe ---------------------------------------------------------------------------------------

def handle_callback(callback: dict, client) -> None:
    chat_id = callback["message"]["chat"]["id"]
    try:
        key, action = callback.get("data", "").split(":", 1)
        draft = BotDraft.objects.select_related("inbound", "person").get(pk=int(key[1:]), chat_id=chat_id)
    except (ValueError, BotDraft.DoesNotExist):
        client.answer_callback(callback["id"], "Vorschlag nicht gefunden")
        return
    if action == "retry" and draft.status == BotDraft.Status.FAILED:
        client.answer_callback(callback["id"], "Neuer Versuch")
        retry_draft(draft, client)
        return
    if action == "x" and draft.status == BotDraft.Status.FAILED:
        discard_draft(draft, client, callback["message"].get("message_id"))
        client.answer_callback(callback["id"], "🗑 Verworfen – Nachricht gelöscht")
        return
    if draft.status != BotDraft.Status.AWAITING:
        client.answer_callback(callback["id"], f"Bereits erledigt ({draft.get_status_display()})")
        return
    if draft.data.get("intent") == "mandate" and "m" in draft.data:
        from .mandates import handle_action
        handle_action(draft, action, callback, client)
        return
    if draft.data.get("intent") == "assign" and "a" in draft.data:
        from .assign import handle_action as handle_assign
        handle_assign(draft, action, callback, client)
        return

    if action.startswith("p") and action[1:].isdigit() and int(action[1:]) in draft.candidates:
        draft.person = Person.objects.get(pk=int(action[1:]))
        draft.save(update_fields=["person", "updated_at"])
        client.answer_callback(callback["id"], "Person gewählt")
        _show(draft, client)
    elif action in ("f0", "f1", "f7"):
        shift_follow_up(draft, int(action[1:]))
        client.answer_callback(callback["id"], "Wiedervorlage geändert")
        _show(draft, client)
    elif action == "ok" and draft.person:
        save_draft(draft)
        client.answer_callback(callback["id"], "Gespeichert")
        _finish(draft, client, "✅ Gespeichert")
    elif action == "np":
        draft.person = None
        save_draft(draft)
        client.answer_callback(callback["id"], "Gespeichert")
        _finish(draft, client, "💾 Gespeichert ohne Person – steht im Briefing unter „Nicht zugeordnet“")
    elif action == "x":
        discard_draft(draft, client, callback["message"].get("message_id"))
        client.answer_callback(callback["id"], "🗑 Verworfen – Nachricht gelöscht")
    else:
        client.answer_callback(callback["id"], "Unbekannte Aktion")


def _finish(draft, client, status_line):
    """Knöpfe am Vorschlag entfernen und die Bestätigung zusätzlich unten im Chat zeigen."""
    text, _ = render(draft)
    try:
        client.edit_message(draft.chat_id, draft.message_id, f"{text}\n\n<b>{status_line}</b>", [])
    except TelegramError as e:
        log.warning("Vorschlag #%s: Bearbeiten fehlgeschlagen (%s)", draft.pk, e)
    summary = escape((draft.data.get("note") or "")[:80])
    who = f" – {escape(str(draft.person))}" if draft.person else ""
    _safe_send(client, draft.chat_id, f"{status_line}\n<i>{summary}{who}</i>")


# --- Speichern ------------------------------------------------------------------------------------

@transaction.atomic
def save_draft(draft: BotDraft) -> None:
    d, item, person = draft.data, draft.inbound, draft.person
    origin = Origin.VOICE if item.channel == InboundItem.Channel.VOICE else Origin.MANUAL
    note = Note.objects.create(person=person, text=d["note"], origin=origin) if person else None
    if d.get("follow_up_date"):
        text = d.get("follow_up_text") or d["note"]
        if not person and d.get("person_name"):
            text = f"{text} ({d['person_name']})"
        FollowUp.objects.create(person=person, due_date=date.fromisoformat(d["follow_up_date"]),
                                reason=FollowUp.Reason.NOTE, text=text[:255], source_note=note)
    item.person = person
    item.status = InboundItem.Status.ASSIGNED if person else InboundItem.Status.UNASSIGNED
    item.processed_at = timezone.now()
    item.save(update_fields=["person", "status", "processed_at", "updated_at"])
    draft.status = BotDraft.Status.SAVED
    draft.save(update_fields=["person", "status", "updated_at"])


def cancel_draft(draft: BotDraft) -> None:
    item = draft.inbound
    item.status, item.processed_at = InboundItem.Status.IGNORED, timezone.now()
    item.save(update_fields=["status", "processed_at", "updated_at"])
    draft.status = BotDraft.Status.CANCELLED
    draft.save(update_fields=["status", "updated_at"])


def discard_draft(draft: BotDraft, client, callback_message_id: int | None = None) -> None:
    """Verwerfen: im Chat (Original, Bot-Meldungen, Vorschlag) und im System löschen (Eingang inkl. Audio)."""
    item = draft.inbound
    ids = set(draft.data.get("_tg", [])) | {i for i in (callback_message_id, draft.message_id) if i}
    if item.external_id.startswith(f"tg-{draft.chat_id}-"):
        try:
            ids.add(int(item.external_id.rsplit("-", 1)[1]))
        except ValueError:
            pass
    for message_id in sorted(ids):
        client.delete_message(draft.chat_id, message_id)  # > 48 h: Telegram lehnt ab, dann bleibt sie stehen
    if item.attachment:
        item.attachment.delete(save=False)
    item.delete()  # löscht auch den Vorschlag (BotDraft hängt am Eingang)


def retry_draft(draft: BotDraft, client) -> None:
    item = draft.inbound
    item.status, item.error = InboundItem.Status.RECEIVED, ""
    item.save(update_fields=["status", "error", "updated_at"])
    draft.status, draft.message_id = BotDraft.Status.PROCESSING, None
    draft.save(update_fields=["status", "message_id", "updated_at"])
    remember_message(draft, _safe_send(client, draft.chat_id, "🔄 Neuer Versuch …"))
    if settings.TELEGRAM_ASYNC:
        from django_q.tasks import async_task
        async_task("apps.bot.processing.process_draft", draft.pk)
    else:
        process_draft(draft.pk, client)


def show_open(chat_id: int, client, limit: int = 5) -> None:
    """/offen: unbestätigte Vorschläge erneut mit Knöpfen anzeigen (z. B. nach Verbindungsproblemen)."""
    drafts = list(BotDraft.objects.filter(chat_id=chat_id, status=BotDraft.Status.AWAITING)
                  .select_related("inbound", "person").order_by("created_at"))
    failed = BotDraft.objects.filter(chat_id=chat_id, status=BotDraft.Status.FAILED).count()
    if not drafts:
        extra = f" ({failed} mit Fehler – im Admin unter Telegram-Vorschläge)" if failed else ""
        client.send_message(chat_id, f"Keine offenen Vorschläge.{extra}")
        return
    more = f" – zeige die ersten {limit}" if len(drafts) > limit else ""
    client.send_message(chat_id, f"<b>{len(drafts)} offene Vorschläge</b>{more}:")
    for draft in drafts[:limit]:
        _show(draft, client, new=True)
