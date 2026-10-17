"""Profil/CV/Shortlist an Kunden: Entwurf, Sperren, Stopp-Fenster, Versand per E-Mail."""
from decimal import Decimal

import pytest
from django.core import mail
from django.core.files.base import ContentFile
from django.utils import timezone

from apps.candidates.models import CandidateProfile, CVDocument
from apps.clients.models import Contract, FeeModel
from apps.communications.models import OutboundMessage
from apps.communications.services import (
    MessageError, prepare_profile_message, schedule_message, send_due_messages, send_now, stop_message,
)
from apps.contacts.models import Company, Person
from apps.jobs.models import Mandate
from apps.pipeline.models import Submission


@pytest.fixture(autouse=True)
def mail_settings(settings, tmp_path):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    settings.DEFAULT_FROM_EMAIL = "vertrag@example.com"
    settings.EMAIL_REPLY_TO = ["sandra@example.com"]
    settings.OUTBOUND_STOP_MINUTES = 60
    settings.TELEGRAM_BOT_TOKEN = ""
    settings.MEDIA_ROOT = str(tmp_path)


@pytest.fixture
def mandate(db):
    company = Company.objects.create(name="Muster AG")
    contact = Person.objects.create(first_name="Karl", last_name="Kunde", email="karl@muster.example")
    mandate = Mandate.objects.create(company=company, contact_person=contact, title="Vertriebsleiter")
    fee = FeeModel.objects.create(name="Einzelauftrag", percent=Decimal("20.00"))
    Contract.objects.create(mandate=mandate, company=company, fee_model=fee, status=Contract.Status.SIGNED)
    return mandate


def candidate(mandate, last_name, consent=True, cv=True):
    person = Person.objects.create(first_name="Anna", last_name=last_name)
    profile = CandidateProfile.objects.create(person=person, headline="Vertriebsleiterin")
    if cv:
        doc = CVDocument(profile=profile)
        doc.file.save(f"cv-{last_name}.pdf", ContentFile(b"%PDF-1.4 test"), save=False)
        doc.save()
    return Submission.objects.create(candidate=profile, mandate=mandate,
                                     consent_to_present_at=timezone.now() if consent else None)


def test_shortlist_one_mail_with_all_cvs(mandate):
    subs = [candidate(mandate, "Eins"), candidate(mandate, "Zwei")]
    msg = prepare_profile_message(subs)
    assert msg.status == OutboundMessage.Status.DRAFT
    assert msg.recipient == mandate.contact_person
    assert msg.attachments.count() == 2
    assert "Kandidatenvorschläge" in msg.subject and "Anna Eins" in msg.body

    send_now(msg)
    assert len(mail.outbox) == 1
    sent = mail.outbox[0]
    assert sent.to == ["karl@muster.example"] and sent.reply_to == ["sandra@example.com"]
    assert len(sent.attachments) == 2
    for sub in subs:
        sub.refresh_from_db()
        assert sub.stage == Submission.Stage.PRESENTED and sub.presented_at


def test_stop_window_then_due_send(mandate):
    msg = prepare_profile_message([candidate(mandate, "Eins")])
    schedule_message(msg)
    assert msg.status == OutboundMessage.Status.SCHEDULED and not mail.outbox
    assert send_due_messages() == 0  # Fenster läuft noch
    OutboundMessage.objects.filter(pk=msg.pk).update(scheduled_for=timezone.now())
    assert send_due_messages() == 1
    msg.refresh_from_db()
    assert msg.status == OutboundMessage.Status.SENT and len(mail.outbox) == 1


def test_stop(mandate):
    msg = prepare_profile_message([candidate(mandate, "Eins")])
    schedule_message(msg)
    stop_message(msg)
    OutboundMessage.objects.filter(pk=msg.pk).update(scheduled_for=timezone.now())
    assert send_due_messages() == 0 and not mail.outbox


def test_blocks_without_consent(mandate):
    msg = prepare_profile_message([candidate(mandate, "Eins", consent=False)])
    with pytest.raises(MessageError, match="Zustimmung"):
        schedule_message(msg)


def test_blocks_without_cv(mandate):
    msg = prepare_profile_message([candidate(mandate, "Eins", cv=False)])
    with pytest.raises(MessageError, match="Lebenslauf"):
        send_now(msg)
    assert not mail.outbox


def test_blocks_without_signed_contract(mandate):
    mandate.contracts.update(status=Contract.Status.DRAFT)
    msg = prepare_profile_message([candidate(mandate, "Eins")])
    with pytest.raises(MessageError, match="Vertrag"):
        send_now(msg)


def test_rejects_mixed_mandates(mandate):
    other = Mandate.objects.create(company=mandate.company, contact_person=mandate.contact_person, title="CFO")
    with pytest.raises(MessageError, match="desselben Auftrags"):
        prepare_profile_message([candidate(mandate, "Eins"), candidate(other, "Zwei")])


def test_smtp_error_marks_failed(mandate, settings, monkeypatch):
    msg = prepare_profile_message([candidate(mandate, "Eins")])

    def boom(*a, **k):
        raise OSError("SMTP down")
    monkeypatch.setattr("django.core.mail.EmailMessage.send", boom)
    with pytest.raises(MessageError, match="SMTP down"):
        send_now(msg)
    msg.refresh_from_db()
    assert msg.status == OutboundMessage.Status.FAILED and "SMTP down" in msg.error
