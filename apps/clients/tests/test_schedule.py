"""Stopp-Fenster vor dem Vertragsversand und automatische Erinnerungen (P1 Punkt 4)."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.clients.models import Contract, FeeModel
from apps.clients.services import (ContractError, schedule_contract, send_contract, send_contract_reminders,
                                   send_due_contracts, stop_contract)
from apps.clients.signature.fake import FakeSignatureProvider
from apps.communications.models import OutboundMessage
from apps.contacts.models import Company, Person
from apps.jobs.models import Mandate


@pytest.fixture(autouse=True)
def cfg(settings, monkeypatch):
    settings.SIGNATURE_PROVIDER = "fake"
    settings.CONTRACT_STOP_MINUTES = 60
    settings.CONTRACT_REMINDER_DAYS = [3, 7]
    settings.TELEGRAM_BOT_TOKEN = ""  # keine Telegram-Hinweise im Test
    monkeypatch.setattr(FakeSignatureProvider, "reminded", [])


@pytest.fixture
def contract(db):
    company = Company.objects.create(name="Muster AG")
    contact = Person.objects.create(first_name="Karl", last_name="Kunde", email="karl@muster.example")
    mandate = Mandate.objects.create(company=company, contact_person=contact, title="Vertriebsleiter")
    fee = FeeModel.objects.create(name="Einzelauftrag", percent=Decimal("20.00"))
    return Contract.objects.create(mandate=mandate, company=company, fee_model=fee)


def test_schedule_waits_for_stop_window(contract):
    schedule_contract(contract)
    contract.refresh_from_db()
    assert contract.status == Contract.Status.SCHEDULED and not contract.signature_provider_id
    assert 59 <= (contract.scheduled_for - timezone.now()).total_seconds() / 60 <= 60
    assert send_due_contracts() == 0  # Fenster läuft noch

    Contract.objects.filter(pk=contract.pk).update(scheduled_for=timezone.now() - timedelta(seconds=1))
    assert send_due_contracts() == 1
    contract.refresh_from_db()
    assert contract.status == Contract.Status.SENT and contract.scheduled_for is None
    assert contract.signature_submitter_id.startswith("fake-sub-")


def test_stop_returns_to_draft(contract):
    schedule_contract(contract)
    stop_contract(contract)
    contract.refresh_from_db()
    assert contract.status == Contract.Status.DRAFT and contract.scheduled_for is None
    Contract.objects.filter(pk=contract.pk).update(scheduled_for=timezone.now() - timedelta(hours=1))
    assert send_due_contracts() == 0
    assert contract.events.filter(kind="stopped").exists()
    with pytest.raises(ContractError):
        stop_contract(contract)


def test_schedule_checks_before_waiting(contract):
    contract.deviations = "18 %"
    contract.save()
    with pytest.raises(ContractError, match="freigegeben"):
        schedule_contract(contract)
    assert Contract.objects.get(pk=contract.pk).status == Contract.Status.DRAFT


def test_send_now_during_window(contract):
    schedule_contract(contract)
    send_contract(contract)
    assert Contract.objects.get(pk=contract.pk).status == Contract.Status.SENT


def test_zero_minutes_sends_immediately(settings, contract):
    settings.CONTRACT_STOP_MINUTES = 0
    schedule_contract(contract)
    assert Contract.objects.get(pk=contract.pk).status == Contract.Status.SENT


def test_failed_due_send_goes_back_to_draft(contract):
    schedule_contract(contract)
    contract.mandate.contact_person.email = ""  # inzwischen ungültig
    contract.mandate.contact_person.save()
    Contract.objects.filter(pk=contract.pk).update(scheduled_for=timezone.now() - timedelta(seconds=1))
    assert send_due_contracts() == 0
    assert Contract.objects.get(pk=contract.pk).status == Contract.Status.DRAFT


def test_reminders_after_3_and_7_days(contract):
    send_contract(contract)
    contract.refresh_from_db()
    sent = contract.sent_at
    assert send_contract_reminders(now=sent + timedelta(days=2)) == 0
    assert send_contract_reminders(now=sent + timedelta(days=3, minutes=1)) == 1
    assert send_contract_reminders(now=sent + timedelta(days=4)) == 0  # 2. erst nach 7 Tagen
    assert send_contract_reminders(now=sent + timedelta(days=7, minutes=1)) == 1
    assert send_contract_reminders(now=sent + timedelta(days=30)) == 0  # nicht mehr als 2
    contract.refresh_from_db()
    assert contract.reminders_sent == 2 and contract.last_reminder_at
    assert FakeSignatureProvider.reminded == [contract.signature_submitter_id] * 2
    assert OutboundMessage.objects.filter(kind=OutboundMessage.Kind.CONTRACT_REMINDER).count() == 2


def test_no_reminder_when_signed(contract):
    send_contract(contract)
    Contract.objects.filter(pk=contract.pk).update(status=Contract.Status.SIGNED)
    assert send_contract_reminders(now=timezone.now() + timedelta(days=10)) == 0


def test_telegram_stop_button(contract, settings):
    from apps.bot.handlers import handle_update

    settings.TELEGRAM_ALLOWED_CHAT_IDS = [4711]
    schedule_contract(contract)

    class Client:
        sent, answers = [], []
        def send_message(self, chat_id, text, buttons=None): self.sent.append(text); return {"message_id": 1}
        def edit_message(self, *a, **k): pass
        def answer_callback(self, cid, text=""): self.answers.append(text)

    client = Client()
    handle_update({"update_id": 1, "callback_query": {"id": "x", "data": f"c{contract.pk}:stop",
                   "message": {"message_id": 5, "chat": {"id": 4711}}}}, client)
    assert Contract.objects.get(pk=contract.pk).status == Contract.Status.DRAFT
    assert "gestoppt" in client.sent[-1]


def test_briefing_lists_active_mandate_without_contract(db):
    from apps.bot.briefing import build_briefing

    company = Company.objects.create(name="Beta GmbH")
    Mandate.objects.create(company=company, title="CTO", status=Mandate.Status.ACTIVE)
    assert "Aktive Aufträge ohne Vertrag (1)" in build_briefing() and "CTO" in build_briefing()
