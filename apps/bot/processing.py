"""Nachricht → Transkript → Vorschlag (Notiz, Person, Wiedervorlage) → Bestätigung per Knopf → Speichern.

Nichts wird ohne Bestätigung in Notizen/Wiedervorlagen übernommen. Der Eingang (InboundItem) mit
Transkript bleibt immer erhalten.
"""
import logging
import time
from datetime import date
from html import escape

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
            client.send_message(draft.chat_id, f"🎙 <i>{escape(item.raw_text[:600])}</i>\n⏳ Werte aus …")
        t0 = time.monotonic()
        draft.data = extract_note(item.raw_text)
        log.info("Vorschlag #%s: Auswertung fertig (%.0f s)", draft.pk, time.monotonic() - t0)
    except LLMError as e:
        _fail(draft, item, str(e), client)
        return draft
    except Exception as e:  # unerwarteter Fehler: nicht „In Verarbeitung“ hängen lassen
        log.exception("Vorschlag #%s: unerwarteter Fehler", draft.pk)
        _fail(draft, item, f"Interner Fehler ({type(e).__name__}: {e})", client)
        return draft

    persons = find_persons(draft.data.get("person_name"), draft.data.get("company"))
    draft.candidates = [p.pk for p in persons]
    draft.person = persons[0] if len(persons) == 1 else None
    draft.status = BotDraft.Status.AWAITING
    draft.save()
    _show(draft, client, new=True)
    return draft


def _fail(draft, item, error, client):
    draft.status = BotDraft.Status.FAILED
    draft.save(update_fields=["status", "updated_at"])
    item.status, item.error, item.processed_at = InboundItem.Status.FAILED, error[:2000], timezone.now()
    item.save(update_fields=["status", "error", "processed_at", "updated_at"])
    hint = f"\n\nTranskript: <i>{escape(item.raw_text[:500])}</i>" if item.raw_text else ""
    client.send_message(draft.chat_id, f"⚠️ Konnte die Nachricht nicht verarbeiten: {escape(error[:300])}\n"
                                       f"Gespeichert als Eingang #{item.pk}.{hint}")


# --- Anzeige ---------------------------------------------------------------------------------------

def render(draft: BotDraft) -> tuple[str, list]:
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
    if draft.inbound.channel == InboundItem.Channel.VOICE:
        lines.append(f"\n🎙 <i>{escape(draft.inbound.raw_text[:200])}</i>")

    key = f"d{draft.pk}"
    buttons = []
    if draft.person:
        buttons.append([("✅ Speichern", f"{key}:ok")])
    elif draft.candidates:
        by_id = {p.pk: p for p in Person.objects.filter(pk__in=draft.candidates).prefetch_related("employments__company")}
        buttons += [[(f"👤 {person_label(by_id[i])}"[:60], f"{key}:p{i}")] for i in draft.candidates if i in by_id]
    buttons.append([("💾 Ohne Person speichern", f"{key}:np"), ("❌ Verwerfen", f"{key}:x")])
    return "\n".join(lines), buttons


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
    if draft.status != BotDraft.Status.AWAITING:
        client.answer_callback(callback["id"], f"Bereits erledigt ({draft.get_status_display()})")
        return

    if action.startswith("p") and action[1:].isdigit() and int(action[1:]) in draft.candidates:
        draft.person = Person.objects.get(pk=int(action[1:]))
        draft.save(update_fields=["person", "updated_at"])
        client.answer_callback(callback["id"], "Person gewählt")
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
        cancel_draft(draft)
        client.answer_callback(callback["id"], "Verworfen")
        _finish(draft, client, "❌ Verworfen (Eingang bleibt als „Ignoriert“ erhalten)")
    else:
        client.answer_callback(callback["id"], "Unbekannte Aktion")


def _finish(draft, client, status_line):
    text, _ = render(draft)
    try:
        client.edit_message(draft.chat_id, draft.message_id, f"{text}\n\n<b>{status_line}</b>", [])
    except TelegramError:
        client.send_message(draft.chat_id, status_line)


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
