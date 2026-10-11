import json
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.clients.models import Contract, ContractEvent, FeeModel
from apps.clients.services import ContractError, fetch_signed_document, handle_webhook, send_contract
from apps.communications.models import OutboundMessage
from apps.contacts.models import Company, Person
from apps.jobs.models import Mandate

SECRET = "s3cret"


@pytest.fixture(autouse=True)
def signature_settings(settings, tmp_path):
    settings.SIGNATURE_PROVIDER = "fake"
    settings.DOCUSEAL_WEBHOOK_SECRET = SECRET
    settings.DOCUSEAL_WEBHOOK_HEADER = "X-Docuseal-Secret"
    settings.MEDIA_ROOT = str(tmp_path)


@pytest.fixture
def contract(db):
    company = Company.objects.create(name="Muster AG")
    contact = Person.objects.create(first_name="Karl", last_name="Kunde", email="karl@muster.example")
    mandate = Mandate.objects.create(company=company, contact_person=contact, title="Vertriebsleiter")
    fee = FeeModel.objects.create(name="Einzelauftrag", percent=Decimal("20.00"))
    return Contract.objects.create(mandate=mandate, company=company, fee_model=fee)


def profile_message(mandate, status=OutboundMessage.Status.SENT):
    return OutboundMessage(
        kind=OutboundMessage.Kind.PROFILE_TO_CLIENT, status=status, recipient=mandate.contact_person,
        mandate=mandate, subject="Profil", body="…",
    )


def webhook(event_type, submission_id, **extra):
    data = {"id": 99, "submission": {"id": submission_id, **extra}} if event_type.startswith("form.") \
        else {"id": submission_id, **extra}
    return {"event_type": event_type, "timestamp": "2026-10-11T12:00:00Z", "data": data}


# --- Sperre -------------------------------------------------------------------------------------

def test_lock_blocks_profile_without_signed_contract(contract):
    with pytest.raises(ValidationError):
        profile_message(contract.mandate).save()
    assert not OutboundMessage.objects.filter(kind=OutboundMessage.Kind.PROFILE_TO_CLIENT).exists()


def test_lock_allows_draft(contract):
    profile_message(contract.mandate, OutboundMessage.Status.DRAFT).save()


def test_lock_requires_mandate(contract):
    msg = profile_message(contract.mandate)
    msg.mandate = None
    with pytest.raises(ValidationError):
        msg.save()


def test_lock_opens_after_signature(contract):
    send_contract(contract)
    handle_webhook(webhook("form.completed", contract.signature_provider_id))
    assert contract.mandate.has_signed_contract
    profile_message(contract.mandate).save()


# --- Versand -------------------------------------------------------------------------------------

def test_send_contract(contract):
    send_contract(contract)
    contract.refresh_from_db()
    assert contract.status == Contract.Status.SENT
    assert contract.signature_provider_id.startswith("fake-")
    assert contract.signing_url
    assert contract.events.filter(kind="sent").exists()
    log = OutboundMessage.objects.get(kind=OutboundMessage.Kind.CONTRACT)
    assert log.is_automatic and log.status == OutboundMessage.Status.SENT


def test_send_requires_approval_for_deviations(contract):
    contract.deviations = "Honorar 18 %"
    contract.save()
    with pytest.raises(ContractError, match="freigegeben"):
        send_contract(contract)


def test_send_requires_signer_email(contract):
    contract.mandate.contact_person.email = ""
    contract.mandate.contact_person.save()
    with pytest.raises(ContractError, match="E-Mail"):
        send_contract(contract)


def test_send_only_drafts(contract):
    send_contract(contract)
    with pytest.raises(ContractError):
        send_contract(contract)


# --- Webhook -------------------------------------------------------------------------------------

def test_webhook_flow_and_idempotency(contract):
    send_contract(contract)
    sid = contract.signature_provider_id
    handle_webhook(webhook("form.viewed", sid))
    contract.refresh_from_db()
    assert contract.status == Contract.Status.PENDING
    handle_webhook(webhook("submission.completed", sid))
    handle_webhook(webhook("form.declined", sid))  # nach Unterschrift ohne Wirkung
    contract.refresh_from_db()
    assert contract.status == Contract.Status.SIGNED and contract.signed_at
    assert contract.events.filter(kind="form.declined").exists()  # aber protokolliert


def test_webhook_declined(contract):
    send_contract(contract)
    handle_webhook(webhook("form.declined", contract.signature_provider_id, ))
    contract.refresh_from_db()
    assert contract.status == Contract.Status.DECLINED
    assert not contract.mandate.has_signed_contract


def test_webhook_unknown_submission(db):
    assert handle_webhook(webhook("form.completed", "unknown")) is None


def test_fetch_signed_document(contract):
    send_contract(contract)
    fetch_signed_document(contract.pk, "https://sign.example/doc.pdf")
    contract.refresh_from_db()
    assert contract.document.read().startswith(b"%PDF")
    assert ContractEvent.objects.filter(contract=contract, kind="document_saved").exists()


def test_webhook_view_checks_secret(client, contract):
    send_contract(contract)
    body = json.dumps(webhook("form.completed", contract.signature_provider_id))
    url = "/clients/docuseal/webhook/"
    assert client.post(url, body, content_type="application/json").status_code == 403
    assert client.post(url, body, content_type="application/json",
                       headers={"X-Docuseal-Secret": "falsch"}).status_code == 403
    assert client.post(url, body, content_type="application/json",
                       headers={"X-Docuseal-Secret": SECRET}).status_code == 200
    contract.refresh_from_db()
    assert contract.status == Contract.Status.SIGNED


def test_webhook_view_rejects_without_configured_secret(client, settings, contract):
    settings.DOCUSEAL_WEBHOOK_SECRET = ""
    resp = client.post("/clients/docuseal/webhook/", "{}", content_type="application/json",
                       headers={"X-Docuseal-Secret": ""})
    assert resp.status_code == 403


def test_media_only_for_staff(client, contract, django_user_model):
    send_contract(contract)
    fetch_signed_document(contract.pk, "https://sign.example/doc.pdf")
    contract.refresh_from_db()
    url = contract.document.url
    assert client.get(url).status_code == 302  # Weiterleitung zum Login
    client.force_login(django_user_model.objects.create_superuser("admin", "a@example.com", "pw"))
    resp = client.get(url)
    assert resp.status_code == 200
    assert b"".join(resp.streaming_content).startswith(b"%PDF-1.4")
