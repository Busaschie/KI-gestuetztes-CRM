"""Kandidat per Bot einem Auftrag zuordnen."""
import pytest

from agents.llm.providers.fake import FakeProvider
from apps.bot.handlers import handle_update
from apps.bot.models import BotDraft
from apps.bot.tests.test_voice import FakeClient, msg_update, press
from apps.candidates.models import CandidateProfile
from apps.communications.models import Note
from apps.contacts.models import Company, Person
from apps.jobs.models import Mandate
from apps.pipeline.models import Submission

ME = 4711


@pytest.fixture(autouse=True)
def bot_settings(settings, tmp_path):
    settings.TELEGRAM_ALLOWED_CHAT_IDS = [ME]
    settings.TELEGRAM_BOT_TOKEN = "test"
    settings.TELEGRAM_ASYNC = False
    settings.LLM_PROVIDER = "fake"
    settings.TRANSCRIBE_PROVIDER = "fake"
    settings.MEDIA_ROOT = str(tmp_path)


@pytest.fixture
def answer(monkeypatch):
    def set_answer(**a):
        monkeypatch.setattr(FakeProvider, "response", {
            "intent": "assign", "person_name": "Huber", "company": "Muster", "position": "Vertriebsleiter",
            "note": "Für Vertriebsleiter vorgemerkt", "follow_up_date": None, "follow_up_text": None, **a})
    return set_answer


@pytest.fixture
def setup(db):
    company = Company.objects.create(name="Muster AG", is_client=True)
    m1 = Mandate.objects.create(company=company, title="Vertriebsleiter", status=Mandate.Status.ACTIVE)
    Mandate.objects.create(company=company, title="CFO", status=Mandate.Status.ACTIVE)
    huber = Person.objects.create(first_name="Anna", last_name="Huber")
    CandidateProfile.objects.create(person=huber)
    return m1, huber


def run(client):
    handle_update(msg_update(text="Huber für Vertriebsleiter Muster vormerken"), client)
    return BotDraft.objects.get()


def test_assign_with_spoken(setup, answer):
    mandate, huber = setup
    answer()
    client = FakeClient()
    draft = run(client)
    assert "Kandidat zuordnen" in client.sent[-1][1] and "Vertriebsleiter" in client.sent[-1][1]
    press(client, f"d{draft.pk}:ok2")
    sub = Submission.objects.get()
    assert sub.mandate == mandate and sub.candidate.person == huber and sub.spoken_with
    assert sub.stage == Submission.Stage.NEW and Note.objects.get().mandate == mandate


def test_already_assigned_no_button(setup, answer):
    mandate, huber = setup
    Submission.objects.create(candidate=huber.candidate_profile, mandate=mandate)
    answer()
    client = FakeClient()
    draft = run(client)
    assert "Bereits zugeordnet" in client.sent[-1][1] and f"d{draft.pk}:ok" not in client.buttons()


def test_choose_mandate_when_ambiguous(setup, answer):
    mandate, huber = setup
    answer(position=None)  # nur Firma → zwei Aufträge
    client = FakeClient()
    draft = run(client)
    assert f"d{draft.pk}:j{mandate.pk}" in client.buttons()
    press(client, f"d{draft.pk}:j{mandate.pk}")
    press(client, f"d{draft.pk}:ok", update_id=1000)
    assert Submission.objects.get().mandate == mandate


def test_non_candidate_not_found(setup, answer):
    Person.objects.create(first_name="Karl", last_name="Kunde")
    answer(person_name="Karl Kunde")
    client = FakeClient()
    draft = run(client)
    assert "kein Kandidat gefunden" in client.sent[-1][1] and f"d{draft.pk}:ok" not in client.buttons()
