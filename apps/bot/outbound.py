"""Knöpfe zu ausgehenden Nachrichten (z. B. Profil an Kunden) im Telegram-Chat: Stopp oder sofort senden."""
from html import escape

from apps.communications.models import OutboundMessage
from apps.communications.services import MessageError, send_now, stop_message


def handle_outbound_callback(callback: dict, client) -> None:
    chat_id = callback["message"]["chat"]["id"]
    message_id = callback["message"].get("message_id")
    try:
        key, action = callback.get("data", "").split(":", 1)
        msg = OutboundMessage.objects.select_related("recipient", "mandate").get(pk=int(key[1:]))
    except (ValueError, OutboundMessage.DoesNotExist):
        client.answer_callback(callback["id"], "Nachricht nicht gefunden")
        return
    try:
        if action == "stop":
            stop_message(msg)
            result = "⛔ Versand gestoppt – im Admin wieder freigeben"
        elif action == "now":
            send_now(msg)
            result = "📤 Versendet"
        else:
            client.answer_callback(callback["id"], "Unbekannte Aktion")
            return
    except MessageError as e:
        client.answer_callback(callback["id"], "Nicht möglich")
        client.send_message(chat_id, f"⚠️ {escape(str(e))}")
        return
    client.answer_callback(callback["id"], result[:60])
    if message_id:
        try:
            client.edit_message(chat_id, message_id, f"{escape(msg.subject)}\n<b>{result}</b>", [])
        except Exception:  # noqa: BLE001 – Bestätigung unten reicht notfalls
            pass
    client.send_message(chat_id, f"{result}\n<i>{escape(msg.subject)}</i>")
