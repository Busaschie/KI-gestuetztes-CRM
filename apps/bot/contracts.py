"""Knöpfe zu Verträgen im Telegram-Chat: geplanten Versand stoppen oder sofort senden."""
from html import escape

from apps.clients.models import Contract
from apps.clients.services import ContractError, send_contract, stop_contract


def handle_contract_callback(callback: dict, client) -> None:
    chat_id = callback["message"]["chat"]["id"]
    message_id = callback["message"].get("message_id")
    try:
        key, action = callback.get("data", "").split(":", 1)
        contract = Contract.objects.select_related("mandate").get(pk=int(key[1:]))
    except (ValueError, Contract.DoesNotExist):
        client.answer_callback(callback["id"], "Vertrag nicht gefunden")
        return
    try:
        if action == "stop":
            stop_contract(contract)
            result = "⛔ Versand gestoppt – Vertrag ist wieder Entwurf"
        elif action == "now":
            send_contract(contract)
            result = "📤 Vertrag versendet"
        else:
            client.answer_callback(callback["id"], "Unbekannte Aktion")
            return
    except ContractError as e:
        client.answer_callback(callback["id"], "Nicht möglich")
        client.send_message(chat_id, f"⚠️ {escape(str(e))}")
        return
    client.answer_callback(callback["id"], result[:60])
    if message_id:
        try:
            client.edit_message(chat_id, message_id, f"{escape(str(contract.mandate))}\n<b>{result}</b>", [])
        except Exception:  # noqa: BLE001 – Bestätigung unten reicht notfalls
            pass
    client.send_message(chat_id, f"{result}\n<i>{escape(str(contract.mandate))}</i>")
