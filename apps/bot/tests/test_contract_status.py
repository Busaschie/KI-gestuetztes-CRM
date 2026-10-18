"""Vertragsstatus per Bot und verpasster Versand (qcluster lief nicht)."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from agents.llm.providers.fake import FakeProvider
from apps.bot.handlers import handle_update
from apps.bot.models import BotDraft
from apps.bot.tests.test_voice import FakeClient, msg_update, press
from apps.clients.models import Contract, ContractEvent, FeeModel
from apps.clients.services import send_due_contracts
from apps.communications.models import OutboundMessage
from apps.communications.services import send_due_messages
from apps.contacts.models import Company, Person
from apps.jobs.models import Mandate

ME = 4711


@pytest.fixture(autouse=True)
def cfg(settings, tmp_path, monkeypatch):
    settings.TELEGRAM_ALLOWED_CHAT_IDS = [ME]
    settings.TELEGRAM_BOT_TOKEN = "test"
    settings.TELEGRAM_ASYNC = False
    settings.LLM_PROVIDER = "fake"
    settings.MEDIA_ROOT = str(tmp_path)
    settings.SEND_MAX_DELAY_MINUTES = 120
    settings.SIGNATURE_PROVIDER = "fake"
    notes = []
    monkeypatch.setattr("apps.clients.services.notify", lambda text, buttons=None: notes.append((text, buttons)))
    return notes


@pytest.fixture
def contracts(db):
    company = Company.objects.create(name="Muster AG")
    fee = FeeModel.objects.create(name="S", percent=Decimal(20))
    out = []
    for title, status in (("Vertriebsleiter", Contract.Status.SIGNED), ("CFO", Contract.Status.SIGNED)):
        m = Mandate.objects.create(company=company, title=title)
        out.append(Contract.objects.create(mandate=m, company=company, fee_model=fee, status=status))
    return out


def answer(monkeypatch, **a):
    monkeypatch.setattr(FakeProvider, "response", {"intent": "contract_status", "company": "Muster AG",
                                                   "note": "bezahlt", **a})


def test_paid_with_position(contracts, monkeypatch):
    answer(monkeypatch, contract_status="paid", position="Vertriebsleiter")
    client = FakeClient()
    handle_update(msg_update(text="Muster AG hat für Vertriebsleiter bezahlt"), client)
    draft = BotDraft.objects.get()
    assert "Bezahlt" in client.sent[-1][1]
    press(client, f"d{draft.pk}:ok")
    contracts[0].refresh_from_db()
    assert contracts[0].status == Contract.Status.PAID and contracts[1].status == Contract.Status.SIGNED
    assert ContractEvent.objects.get(kind="status").message.startswith("Unterschrieben → Bezahlt")


def test_choose_when_several_and_invoice(contracts, monkeypatch):
    answer(monkeypatch, contract_status="invoice_due")
    client = FakeClient()
    handle_update(msg_update(text="Rechnung an Muster AG ist raus"), client)
    draft = BotDraft.objects.get()
    press(client, f"d{draft.pk}:v{contracts[1].pk}")
    press(client, f"d{draft.pk}:ok", update_id=1000)
    contracts[1].refresh_from_db()
    assert contracts[1].status == Contract.Status.INVOICE_DUE


def test_unclear_status_becomes_note(contracts, monkeypatch):
    answer(monkeypatch, contract_status="vielleicht")
    client = FakeClient()
    handle_update(msg_update(text="Muster AG irgendwas"), client)
    assert BotDraft.objects.get().data["intent"] == "note"


def test_missed_contract_not_sent_late(contracts, cfg):
    c = contracts[0]
    c.status, c.scheduled_for = Contract.Status.SCHEDULED, timezone.now() - timedelta(hours=5)
    c.save()
    assert send_due_contracts() == 0
    c.refresh_from_db()
    assert c.status == Contract.Status.DRAFT and ContractEvent.objects.filter(contract=c, kind="missed").exists()
    assert "verpasst" in cfg[-1][0] and cfg[-1][1][0][0][1] == f"c{c.pk}:now"


def test_missed_message_not_sent_late(db, settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    from django.core import mail
    p = Person.objects.create(last_name="X", email="x@example.com")
    msg = OutboundMessage.objects.create(kind=OutboundMessage.Kind.OTHER, status=OutboundMessage.Status.SCHEDULED,
                                         recipient=p, subject="Hallo", body="…", approved_at=timezone.now(),
                                         scheduled_for=timezone.now() - timedelta(hours=3))
    assert send_due_messages() == 0 and not mail.outbox
    msg.refresh_from_db()
    assert msg.status == OutboundMessage.Status.STOPPED and "verpasst" in msg.error
