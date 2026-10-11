"""Verarbeitet eingehende Telegram-Nachrichten. Nur freigegebene Chat-IDs werden bedient."""
import logging
from django.conf import settings
from django.utils import timezone

from apps.communications.models import InboundItem

from .briefing import build_briefing

log = logging.getLogger(__name__)

HELP = (
    "<b>Befehle</b>\n"
    "/briefing – aktuelles Briefing\n"
    "/id – deine Chat-ID\n"
    "/hilfe – diese Übersicht\n\n"
    "Textnachrichten werden als Eingang gespeichert. Sprachnachrichten folgen in Kürze."
)


COMMANDS = [
    ("briefing", "Aktuelles Briefing"),
    ("id", "Eigene Chat-ID anzeigen"),
    ("hilfe", "Befehlsübersicht"),
]


def is_allowed(chat_id: int) -> bool:
    return chat_id in settings.TELEGRAM_ALLOWED_CHAT_IDS


def handle_update(update: dict, client) -> None:
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

    if command in ("/hilfe", "/help"):
        client.send_message(chat_id, HELP)
    elif command == "/briefing":
        client.send_message(chat_id, build_briefing())
    elif command:
        client.send_message(chat_id, "Unbekannter Befehl. /hilfe zeigt alle Befehle.")
    elif "voice" in msg or "audio" in msg:
        client.send_message(chat_id, "Sprachnachrichten kann ich noch nicht verarbeiten – kommt in der nächsten Ausbaustufe.")
    elif text:
        item = _save_text(msg, chat_id, text)
        client.send_message(chat_id, f"Gespeichert als Eingang #{item.pk} (noch nicht zugeordnet).")
    else:
        client.send_message(chat_id, "Diesen Nachrichtentyp kann ich noch nicht verarbeiten.")


def _save_text(msg: dict, chat_id: int, text: str) -> InboundItem:
    external_id = f"tg-{chat_id}-{msg['message_id']}"
    item, _ = InboundItem.objects.get_or_create(  # Telegram kann Nachrichten erneut zustellen
        external_id=external_id,
        defaults={
            "channel": InboundItem.Channel.TELEGRAM,
            "status": InboundItem.Status.UNASSIGNED,
            "subject": text[:80],
            "sender": (msg.get("from") or {}).get("first_name", "")[:255],
            "raw_text": text,
            "processed_at": timezone.now(),
        },
    )
    return item
