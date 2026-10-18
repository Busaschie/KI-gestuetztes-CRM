"""Kontaktpflege: letzter Kontakt, Regeln (vermittelt / frühere Kunden / vorgemerkt), Vorschläge im Briefing."""
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.bot.briefing import build_briefing, send_briefing
from apps.bot.handlers import handle_update
from apps.candidates.models import CandidateProfile
from apps.communications.contact_care import plan_contact_care, suggestions
from apps.communications.models import FollowUp, Note
from apps.contacts.models import Company, Employment, Person
from apps.jobs.models import Mandate
from apps.pipeline.models import Submission

ME = 4711


class Client:
    def __init__(self):
        self.sent, self.edits, self.answers = [], [], []

    def send_message(self, chat_id, text, buttons=None):
        self.sent.append((text, buttons))
        return {"message_id": len(self.sent)}

    def edit_message(self, chat_id, message_id, text, buttons=None):
        self.edits.append(text)

    def answer_callback(self, cid, text=""):
        self.answers.append(text)


@pytest.fixture(autouse=True)
def cfg(settings):
    settings.CONTACT_CARE_MONTHS_PLACED = 6
    settings.CONTACT_CARE_MONTHS_CLIENTS = 4
    settings.CONTACT_SUGGESTIONS_PER_DAY = 3
    settings.TELEGRAM_ALLOWED_CHAT_IDS = [ME]
    settings.TELEGRAM_BOT_TOKEN = "test"


def ago(days):
    return timezone.now() - timedelta(days=days)


def person(name, contacted_days=None):
    p = Person.objects.create(last_name=name)
    Person.objects.filter(pk=p.pk).update(created_at=ago(1000),
                                          last_contacted_at=ago(contacted_days) if contacted_days else None)
    return Person.objects.get(pk=p.pk)


@pytest.fixture
def world(db):
    company = Company.objects.create(name="Alt AG", is_client=True)
    running = Company.objects.create(name="Lauf AG", is_client=True)
    placed = person("Vermittelt", 200)
    cand = CandidateProfile.objects.create(person=placed)
    old_m = Mandate.objects.create(company=company, title="CFO", status=Mandate.Status.FILLED)
    Submission.objects.create(candidate=cand, mandate=old_m, stage=Submission.Stage.PLACED)
    former = person("Frueher", 130)
    Employment.objects.create(person=former, company=company)
    recent = person("Neulich", 30)
    Employment.objects.create(person=recent, company=company)
    active = person("Aktiv", 300)
    Mandate.objects.create(company=running, contact_person=active, title="CTO", status=Mandate.Status.ACTIVE)
    return placed, former, recent, active


def test_rules(world):
    placed, former, recent, active = world
    assert plan_contact_care() == 2
    names = set(FollowUp.objects.values_list("person__last_name", flat=True))
    assert names == {"Vermittelt", "Frueher"}  # nicht: kürzlich kontaktiert, Kunde mit laufendem Auftrag
    assert "vermittelt" in FollowUp.objects.get(person=placed).text
    assert plan_contact_care() == 0  # keine doppelten


def test_note_sets_last_contact_and_opt_out(world):
    placed, former, *_ = world
    Note.objects.create(person=placed, text="Telefoniert")
    former.no_contact_care = True
    former.save()
    assert plan_contact_care() == 0


def test_on_hold_once_per_date(db):
    p = person("Vorgemerkt")
    CandidateProfile.objects.create(person=p, on_hold_until=timezone.localdate())
    assert plan_contact_care() == 1
    FollowUp.objects.update(done_at=timezone.now())
    assert plan_contact_care() == 0


def test_briefing_max_three_and_buttons(db):
    company = Company.objects.create(name="Alt AG", is_client=True)
    for i in range(5):
        Employment.objects.create(person=person(f"K{i}", 200), company=company)
    plan_contact_care()
    assert suggestions().count() == 5
    assert "Kontaktvorschläge (3 von 5)" in build_briefing()
    client = Client()
    send_briefing(ME, client)
    cards = [s for s in client.sent if s[0].startswith("🤝")]
    assert len(cards) == 3
    fu_id = int(cards[0][1][0][0][1].split(":")[0][1:])
    handle_update({"update_id": 1, "callback_query": {"id": "c", "data": f"k{fu_id}:done",
                   "message": {"message_id": 2, "chat": {"id": ME}}}}, client)
    fu = FollowUp.objects.get(pk=fu_id)
    assert fu.done_at and fu.person.last_contacted_at.date() == timezone.localdate()
    second = int(cards[1][1][1][0][1].split(":")[0][1:])
    handle_update({"update_id": 2, "callback_query": {"id": "c", "data": f"k{second}:off",
                   "message": {"message_id": 3, "chat": {"id": ME}}}}, client)
    assert FollowUp.objects.get(pk=second).person.no_contact_care
    assert suggestions().count() == 3
