"""Kontaktvorschläge (Kontaktpflege) im Telegram-Chat: Erledigt, In 1 Monat, Keine Kontaktpflege."""
from html import escape

from apps.communications.contact_care import mark_done, opt_out, postpone
from apps.communications.models import FollowUp


def render_suggestion(fu: FollowUp) -> tuple[str, list]:
    who = escape(str(fu.person)) if fu.person else "?"
    text = f"🤝 <b>Kontaktvorschlag: {who}</b>\n{escape(fu.text)}"
    buttons = [[("✅ Kontakt erledigt", f"k{fu.pk}:done")],
               [("⏭ In 1 Monat", f"k{fu.pk}:m1"), ("🚫 Keine Kontaktpflege", f"k{fu.pk}:off")]]
    return text, buttons


def handle_followup_callback(callback: dict, client) -> None:
    chat_id = callback["message"]["chat"]["id"]
    message_id = callback["message"].get("message_id")
    try:
        key, action = callback.get("data", "").split(":", 1)
        fu = FollowUp.objects.select_related("person").get(pk=int(key[1:]))
    except (ValueError, FollowUp.DoesNotExist):
        client.answer_callback(callback["id"], "Vorschlag nicht gefunden")
        return
    if fu.done_at:
        client.answer_callback(callback["id"], "Bereits erledigt")
        return
    if action == "done":
        mark_done(fu)
        result = "✅ Kontakt erledigt – nächster Vorschlag frühestens in einigen Monaten"
    elif action == "m1":
        postpone(fu, 30)
        result = f"⏭ Verschoben auf {fu.due_date:%d.%m.%Y}"
    elif action == "off":
        opt_out(fu)
        result = "🚫 Keine Kontaktpflege mehr für diese Person"
    else:
        client.answer_callback(callback["id"], "Unbekannte Aktion")
        return
    client.answer_callback(callback["id"], result[:60])
    text, _ = render_suggestion(fu)
    if message_id:
        try:
            client.edit_message(chat_id, message_id, f"{text}\n\n<b>{result}</b>", [])
        except Exception:  # noqa: BLE001
            pass
