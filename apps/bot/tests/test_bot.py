from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.bot.briefing import build_briefing, send_daily_briefing
from apps.bot.handlers import handle_update
from apps.clients.models import Contract, FeeModel
from apps.communications.models import FollowUp, InboundItem
from apps.contacts.models import Company, Person
from apps.jobs.models import Mandate

ME = 4711


class FakeClient:
    def __init__(self):
        self.sent = []

    def send_message(self, chat_id, text, buttons=None):
        self.sent.append((chat_id, text))
        return {"message_id": len(self.sent)}


@pytest.fixture(autouse=True)
def bot_settings(settings):
    settings.TELEGRAM_ALLOWED_CHAT_IDS = [ME]
    settings.TELEGRAM_BOT_TOKEN = "test"


def update(text=None, chat_id=ME, message_id=1, **extra):
    msg = {"message_id": message_id, "chat": {"id": chat_id}, "from": {"first_name": "Niko"}, **extra}
    if text is not None:
        msg["text"] = text
    return {"update_id": 100 + message_id, "message": msg}


# --- Zugriff -------------------------------------------------------------------------------------

def test_start_shows_chat_id_for_anyone(db):
    client = FakeClient()
    handle_update(update("/start", chat_id=999), client)
    assert "999" in client.sent[0][1] and "nicht freigeschaltet" in client.sent[0][1]


def test_unknown_chat_is_ignored(db):
    client = FakeClient()
    handle_update(update("Hallo", chat_id=999), client)
    assert client.sent == []
    assert not InboundItem.objects.exists()


# --- Nachrichten ---------------------------------------------------------------------------------

def test_commands(db):
    client = FakeClient()
    handle_update(update("/hilfe"), client)
    handle_update(update("/briefing"), client)
    handle_update(update("/gibtsnicht"), client)
    assert "Befehle" in client.sent[0][1]
    assert "Briefing" in client.sent[1][1]
    assert "Unbekannter Befehl" in client.sent[2][1]


# --- Briefing ------------------------------------------------------------------------------------

def test_briefing_empty(db):
    assert "nichts Dringendes" in build_briefing()


def test_briefing_content(db):
    today = date(2026, 10, 12)
    person = Person.objects.create(first_name="Eva", last_name="<Meier>")
    FollowUp.objects.create(person=person, due_date=today - timedelta(days=2), text="Zurückrufen")
    FollowUp.objects.create(person=person, due_date=today + timedelta(days=5), text="Später")
    FollowUp.objects.create(person=person, due_date=today, text="Erledigt", done_at=timezone.now())
    InboundItem.objects.create(channel=InboundItem.Channel.EMAIL, status=InboundItem.Status.UNASSIGNED,
                               subject="Bewerbung ohne CV")
    InboundItem.objects.create(channel=InboundItem.Channel.EMAIL, status=InboundItem.Status.ASSIGNED, subject="ok")
    company = Company.objects.create(name="Muster AG")
    mandate = Mandate.objects.create(company=company, title="CFO")
    fee = FeeModel.objects.create(name="Std", percent=Decimal("20"))
    Contract.objects.create(mandate=mandate, company=company, fee_model=fee, status=Contract.Status.SENT,
                            sent_at=timezone.now() - timedelta(days=5))

    text = build_briefing(today)
    assert "Wiedervorlagen (1)" in text and "Zurückrufen" in text and "⚠️" in text
    assert "Später" not in text and "Erledigt" not in text
    assert "&lt;Meier&gt;" in text  # HTML wird escaped
    assert "Nicht zugeordnet (1)" in text and "Bewerbung ohne CV" in text
    assert "Verträge ohne Unterschrift (1)" in text and "CFO" in text


def test_send_daily_briefing(db, monkeypatch):
    sent = []
    monkeypatch.setattr("apps.bot.telegram.TelegramClient.send_message", lambda self, c, t: sent.append(c))
    assert send_daily_briefing() == 1
    assert sent == [ME]


def test_get_updates_passes_long_poll_timeout(monkeypatch):
    from apps.bot.telegram import TelegramClient
    seen = {}

    class Resp:
        def json(self):
            return {"ok": True, "result": []}

    def fake_post(url, json, timeout):
        seen.update(json=json, timeout=timeout)
        return Resp()

    monkeypatch.setattr("apps.bot.telegram.httpx.post", fake_post)
    assert TelegramClient("t").get_updates(offset=5, timeout=50) == []
    assert seen["json"]["timeout"] == 50 and seen["json"]["offset"] == 5 and seen["timeout"] == 60
