"""P1 Punkt 4: neuer Auftrag per Bot → Auftrag + Vertrag (mit Bestätigung und Stopp-Fenster)."""
from decimal import Decimal

import pytest

from agents.llm.providers.fake import FakeProvider
from apps.bot.handlers import handle_update
from apps.bot.models import BotDraft
from apps.bot.tests.test_voice import FakeClient, msg_update, press
from apps.clients.models import Contract, FeeModel
from apps.contacts.models import Company, Employment, Person
from apps.jobs.models import Mandate

ME = 4711


@pytest.fixture(autouse=True)
def bot_settings(settings, tmp_path):
    settings.TELEGRAM_ALLOWED_CHAT_IDS = [ME]
    settings.TELEGRAM_BOT_TOKEN = "test"
    settings.TELEGRAM_ASYNC = False
    settings.LLM_PROVIDER = "fake"
    settings.TRANSCRIBE_PROVIDER = "fake"
    settings.MEDIA_ROOT = str(tmp_path)
    settings.CONTRACTOR_NAME = "Sandra Test SRL"
    settings.CONTRACT_STOP_MINUTES = 60
    settings.SIGNATURE_PROVIDER = "fake"


@pytest.fixture
def mandate_llm(monkeypatch):
    def set_answer(**answer):
        monkeypatch.setattr(FakeProvider, "response", {
            "intent": "mandate", "person_name": None, "company": None, "note": "Neuer Auftrag",
            "follow_up_date": None, "follow_up_text": None, "position": "Vertriebsleiter", "location": "Wien",
            "fee_percent": None, **answer})
    return set_answer


@pytest.fixture
def fees(db):
    return (FeeModel.objects.create(name="Einzelauftrag", percent=Decimal("20"), is_default=True),
            FeeModel.objects.create(name="Mehrere Positionen", percent=Decimal("15")))


@pytest.fixture
def muster(db):
    company = Company.objects.create(name="Muster AG", street="Ring 1", postal_code="1010", city="Wien", country="AT")
    meier = Person.objects.create(first_name="Karl", last_name="Meier", email="meier@muster.example")
    Employment.objects.create(person=meier, company=company)
    return company, meier


def run(client, text="Neuer Auftrag"):
    handle_update(msg_update(text=text), client)
    return BotDraft.objects.get()


def test_known_company_contract_scheduled(fees, muster, mandate_llm, monkeypatch):
    notes = []
    monkeypatch.setattr("apps.clients.services.notify", lambda text, buttons=None: notes.append((text, buttons)))
    company, meier = muster
    mandate_llm(company="Muster", person_name="Meier", fee_percent=15)
    client = FakeClient()
    draft = run(client)
    text = client.sent[-1][1]
    assert "Neuer Auftrag" in text and "Muster AG" in text and "Mehrere Positionen" in text
    assert f"d{draft.pk}:ms" in client.buttons()
    press(client, f"d{draft.pk}:ms")
    mandate = Mandate.objects.get()
    assert mandate.company == company and mandate.contact_person == meier and mandate.status == Mandate.Status.ACTIVE
    contract = Contract.objects.get()
    assert contract.status == Contract.Status.SCHEDULED and contract.fee_model.percent == 15
    assert "Vertrag geht um" in notes[0][0] and notes[0][1][0][0][1] == f"c{contract.pk}:stop"


def test_deviation_needs_explicit_approval(fees, muster, mandate_llm, monkeypatch):
    monkeypatch.setattr("apps.clients.services.notify", lambda *a, **k: None)
    mandate_llm(company="Muster AG", person_name="Karl Meier", fee_percent=25)
    client = FakeClient()
    draft = run(client)
    assert "Abweichung" in client.sent[-1][1] and "Honorar 25 % statt 20 %" in client.sent[-1][1]
    press(client, f"d{draft.pk}:ms")
    contract = Contract.objects.get()
    assert contract.fee_percent == 25 and not contract.deviations and contract.percent == 25
    assert contract.approved_at and contract.status == Contract.Status.SCHEDULED


def test_unknown_company_and_contact_only_mandate(fees, mandate_llm):
    mandate_llm(company="Neufirma GmbH", person_name="Frau Anna Neu")
    client = FakeClient()
    draft = run(client)
    text = client.sent[-1][1]
    assert "wird nur mit Namen angelegt" in text and "Vertrag noch nicht sendbar" in text
    assert f"d{draft.pk}:ms" not in client.buttons()
    press(client, f"d{draft.pk}:mo")
    company = Company.objects.get(name="Neufirma GmbH")
    contact = Person.objects.get(last_name="Neu")
    assert contact.first_name == "Anna" and contact.employments.get().company == company
    mandate = Mandate.objects.get()
    assert mandate.contact_person == contact and Contract.objects.get().status == Contract.Status.DRAFT


def test_choose_company(fees, mandate_llm):
    Company.objects.create(name="Alpha Bau")
    b = Company.objects.create(name="Alpha Baut")
    mandate_llm(company="Alpha Bau")
    client = FakeClient()
    draft = run(client)
    if f"d{draft.pk}:c{b.pk}" in client.buttons():  # mehrere Treffer → wählen
        assert f"d{draft.pk}:mo" not in client.buttons()
        press(client, f"d{draft.pk}:c{b.pk}")
        draft.refresh_from_db()
        assert draft.data["m"]["company_id"] == b.pk
    assert f"d{draft.pk}:mo" in client.buttons()


def test_cancel(fees, muster, mandate_llm):
    mandate_llm(company="Muster")
    client = FakeClient()
    draft = run(client)
    press(client, f"d{draft.pk}:x")
    assert not Mandate.objects.exists() and not BotDraft.objects.exists()


def test_note_intent_unchanged(fees, monkeypatch):
    monkeypatch.setattr(FakeProvider, "response", {"note": "Nur eine Notiz", "fee_percent": "zwanzig"})
    client = FakeClient()
    draft = run(client, "Nur eine Notiz")
    assert draft.data["intent"] == "note" and draft.data["fee_percent"] is None
    assert "Notiz" in client.sent[-1][1] and not Mandate.objects.exists()
