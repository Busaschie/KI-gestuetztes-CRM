"""Standardabsage: Auswahl, Planung für morgen, Stopp, Überholt-Prüfung, Versand, Sprache."""
from datetime import timedelta

import pytest
from django.core import mail
from django.utils import timezone

from apps.candidates.models import CandidateProfile
from apps.communications.models import OutboundMessage
from apps.communications.rejections import due_submissions, prepare_standard_rejections
from apps.communications.services import send_due_messages, stop_message
from apps.contacts.models import Company, Person
from apps.jobs.models import Mandate
from apps.pipeline.models import Submission


@pytest.fixture(autouse=True)
def rejection_settings(settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    settings.DEFAULT_FROM_EMAIL = "vertrag@example.com"
    settings.TELEGRAM_BOT_TOKEN = ""
    settings.STANDARD_REJECTION_ENABLED = True
    settings.STANDARD_REJECTION_DAYS = 10
    settings.STANDARD_REJECTION_TIME = "10:00"
    settings.CONTRACTOR_SIGNER = "Sandra"


@pytest.fixture
def mandate(db):
    company = Company.objects.create(name="Muster AG")
    return Mandate.objects.create(company=company, title="Vertriebsleiter")


def sub(mandate, name, days=11, lang="", email=True, **kw):
    person = Person.objects.create(first_name="Eva", last_name=name, preferred_language=lang,
                                   email=f"{name.lower()}@example.com" if email else "")
    s = Submission.objects.create(candidate=CandidateProfile.objects.create(person=person), mandate=mandate, **kw)
    Submission.objects.filter(pk=s.pk).update(created_at=timezone.now() - timedelta(days=days))
    s.refresh_from_db()
    return s


def run_due():
    OutboundMessage.objects.filter(kind=OutboundMessage.Kind.STANDARD_REJECTION).update(scheduled_for=timezone.now())
    return send_due_messages()


def test_selection(mandate):
    due = sub(mandate, "Faellig")
    sub(mandate, "Frisch", days=3)
    sub(mandate, "Gesprochen", spoken_with=True)
    sub(mandate, "Imgespraech", stage=Submission.Stage.IN_TALKS)
    assert list(due_submissions()) == [due]


def test_disabled_does_nothing(mandate, settings):
    settings.STANDARD_REJECTION_ENABLED = False
    sub(mandate, "Faellig")
    assert prepare_standard_rejections() == 0


def test_planned_for_tomorrow_then_sent(mandate):
    s = sub(mandate, "Faellig")
    assert prepare_standard_rejections() == 1
    msg = OutboundMessage.objects.get(kind=OutboundMessage.Kind.STANDARD_REJECTION)
    local = timezone.localtime(msg.scheduled_for)
    assert local.date() == timezone.localdate() + timedelta(days=1) and (local.hour, local.minute) == (10, 0)
    assert msg.is_automatic and "Vertriebsleiter" in msg.subject
    s.refresh_from_db()
    assert s.stage == Submission.Stage.REJECTION_PREPARED
    assert send_due_messages() == 0  # erst morgen
    assert run_due() == 1
    s.refresh_from_db()
    assert s.stage == Submission.Stage.REJECTED and s.last_feedback_at
    assert mail.outbox[0].to == ["faellig@example.com"]
    assert prepare_standard_rejections() == 0  # nicht doppelt


def test_stop_resets_and_never_again(mandate):
    s = sub(mandate, "Faellig")
    prepare_standard_rejections()
    stop_message(OutboundMessage.objects.get(kind=OutboundMessage.Kind.STANDARD_REJECTION))
    s.refresh_from_db()
    assert s.stage == Submission.Stage.NEW
    assert prepare_standard_rejections() == 0
    assert run_due() == 0 and not mail.outbox


def test_obsolete_if_sandra_changed_stage(mandate):
    s = sub(mandate, "Faellig")
    prepare_standard_rejections()
    Submission.objects.filter(pk=s.pk).update(stage=Submission.Stage.IN_TALKS)
    assert run_due() == 0 and not mail.outbox
    msg = OutboundMessage.objects.get(kind=OutboundMessage.Kind.STANDARD_REJECTION)
    assert msg.status == OutboundMessage.Status.STOPPED and "entfällt" in msg.error


def test_language_and_no_email(mandate):
    sub(mandate, "English", lang="en")
    sub(mandate, "Ohnemail", email=False)
    assert prepare_standard_rejections() == 1
    msg = OutboundMessage.objects.get(kind=OutboundMessage.Kind.STANDARD_REJECTION)
    assert msg.subject.startswith("Your application") and msg.body.startswith("Dear Eva English")
