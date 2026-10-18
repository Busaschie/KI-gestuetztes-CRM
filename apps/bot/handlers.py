"""Verarbeitet eingehende Telegram-Nachrichten. Nur freigegebene Chat-IDs werden bedient."""
import logging

from django.conf import settings
from django.core.files.base import ContentFile

from apps.communications.models import InboundItem

from .briefing import build_briefing, send_briefing
from .models import BotDraft
from .processing import handle_callback, process_draft, remember_message, show_open

log = logging.getLogger(__name__)

HELP = (
    "<b>Befehle</b>\n"
    "/briefing – aktuelles Briefing\n"
    "/offen – unbestätigte Vorschläge erneut anzeigen\n"
    "/status – Einstellungen des Bots\n"
    "/id – deine Chat-ID\n"
    "/hilfe – diese Übersicht\n\n"
    "Sprach- oder Textnachricht schicken – gespeichert wird erst nach deiner Bestätigung:\n"
    "• Notiz: „Mit Eva Meier telefoniert, will nächste Woche Rückmeldung“\n"
    "• Neuer Auftrag: „Neuer Auftrag von Muster AG, Vertriebsleiter in Wien, Ansprechpartner Herr Meier, 20 Prozent“\n"
    "• Kandidat zuordnen: „Anna Huber für Vertriebsleiter Muster AG vormerken“\n"
    "• Vertragsstatus: „Rechnung an Muster AG ist raus“ / „Muster AG hat bezahlt“"
)


COMMANDS = [
    ("briefing", "Aktuelles Briefing"),
    ("offen", "Unbestätigte Vorschläge anzeigen"),
    ("status", "Einstellungen des Bots"),
    ("id", "Eigene Chat-ID anzeigen"),
    ("hilfe", "Befehlsübersicht"),
]


def is_allowed(chat_id: int) -> bool:
    return chat_id in settings.TELEGRAM_ALLOWED_CHAT_IDS


def handle_update(update: dict, client) -> None:
    if cb := update.get("callback_query"):
        chat_id = ((cb.get("message") or {}).get("chat") or {}).get("id")
        if chat_id and is_allowed(chat_id):
            if cb.get("data", "").startswith("c"):
                from .contracts import handle_contract_callback
                handle_contract_callback(cb, client)
            elif cb.get("data", "").startswith("k"):
                from .followups import handle_followup_callback
                handle_followup_callback(cb, client)
            elif cb.get("data", "").startswith("o"):
                from .outbound import handle_outbound_callback
                handle_outbound_callback(cb, client)
            else:
                handle_callback(cb, client)
        return
    msg = update.get("message")
    if not msg or "chat" not in msg:
        return
    chat_id = msg["chat"]["id"]
    text = (msg.get("text") or "").strip()
    command = text.split()[0].split("@")[0].lower() if text.startswith("/") else ""

    if command in ("/start", "/id"):
        state = "freigeschaltet ✅" if is_allowed(chat_id) else "noch nicht freigeschaltet"
        client.send_message(chat_id, f"Deine Chat-ID: <code>{chat_id}</code>\nStatus: {state}")
        return
    if not is_allowed(chat_id):
        log.warning("Telegram: Nachricht von nicht freigegebener Chat-ID %s ignoriert", chat_id)
        return

    if command in ("/", "/hilfe", "/help"):
        client.send_message(chat_id, HELP)
    elif command == "/briefing":
        send_briefing(chat_id, client)
    elif command == "/offen":
        show_open(chat_id, client)
    elif command == "/status":
        client.send_message(chat_id, status_text())
    elif command:
        client.send_message(chat_id, "Unbekannter Befehl. /hilfe zeigt alle Befehle.")
    elif "voice" in msg or "audio" in msg:
        _start(_save_voice(msg, chat_id, client), chat_id, client, "🎙 Sprachnachricht erhalten – verarbeite …")
    elif text:
        _start(_save_text(msg, chat_id, text), chat_id, client, "⏳ Verarbeite …")
    else:
        client.send_message(chat_id, "Diesen Nachrichtentyp kann ich noch nicht verarbeiten.")


def _start(item: InboundItem | None, chat_id: int, client, ack: str) -> None:
    if item is None or hasattr(item, "bot_draft"):
        return  # Telegram hat die Nachricht erneut zugestellt – schon in Arbeit
    draft = BotDraft.objects.create(chat_id=chat_id, inbound=item)
    remember_message(draft, client.send_message(chat_id, ack))
    if settings.TELEGRAM_ASYNC:
        from django_q.tasks import async_task
        async_task("apps.bot.processing.process_draft", draft.pk)
    else:
        process_draft(draft.pk, client)


def _sender(msg: dict) -> str:
    return (msg.get("from") or {}).get("first_name", "")[:255]


def _save_text(msg: dict, chat_id: int, text: str) -> InboundItem:
    item, _ = InboundItem.objects.get_or_create(
        external_id=f"tg-{chat_id}-{msg['message_id']}",
        defaults={"channel": InboundItem.Channel.TELEGRAM, "status": InboundItem.Status.RECEIVED,
                  "subject": text[:80], "sender": _sender(msg), "raw_text": text},
    )
    return item


def _save_voice(msg: dict, chat_id: int, client) -> InboundItem | None:
    external_id = f"tg-{chat_id}-{msg['message_id']}"
    if item := InboundItem.objects.filter(external_id=external_id).first():
        return item
    audio = msg.get("voice") or msg.get("audio")
    data, filename = client.download_file(audio["file_id"])
    item = InboundItem(channel=InboundItem.Channel.VOICE, status=InboundItem.Status.RECEIVED,
                       external_id=external_id, sender=_sender(msg), subject="Sprachnachricht")
    item.attachment.save(filename, ContentFile(data), save=False)  # Original bleibt erhalten
    item.save()
    return item


def status_text() -> str:
    """Aktuelle Einstellungen – geändert werden sie in der .env (danach Bot neu starten)."""
    llm = settings.LLM_PROVIDER
    llm_model = {"mistral": settings.MISTRAL_MODEL, "ollama": settings.OLLAMA_MODEL}.get(llm, "–")
    tr = settings.TRANSCRIBE_PROVIDER
    tr_model = {"whisper": settings.WHISPER_MODEL, "mistral": settings.MISTRAL_TRANSCRIBE_MODEL}.get(tr, "–")
    open_count = BotDraft.objects.filter(status=BotDraft.Status.AWAITING).count()
    failed_count = BotDraft.objects.filter(status=BotDraft.Status.FAILED).count()
    return (
        "<b>Einstellungen</b>\n"
        f"Sprachmodell: {llm} ({llm_model})\n"
        f"Spracherkennung: {tr} ({tr_model}), Sprache: {settings.TRANSCRIBE_LANGUAGE or 'automatisch'}, "
        f"Namenshinweise: {settings.TRANSCRIBE_NAME_HINTS}\n"
        f"Briefing täglich: {settings.TELEGRAM_BRIEFING_TIME} ({settings.TIME_ZONE})\n"
        f"Verarbeitung: {'über qcluster' if settings.TELEGRAM_ASYNC else 'direkt im Bot'}\n"
        f"Offene Vorschläge: {open_count}, mit Fehler: {failed_count}\n\n"
        "<i>Ändern in der .env, danach Bot neu starten.</i>"
    )
