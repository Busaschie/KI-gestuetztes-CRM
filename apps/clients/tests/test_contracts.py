import json
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.clients.models import Contract, ContractEvent, FeeModel
from apps.clients.services import ContractError, fetch_signed_document, handle_documenso_webhook, send_contract
from apps.communications.models import OutboundMessage
from apps.contacts.models import Company, Person
from apps.jobs.models import Mandate

SECRET = "s3cret"


@pytest.fixture(autouse=True)
def signature_settings(settings, tmp_path):
    settings.SIGNATURE_PROVIDER = "fake"
    settings.DOCUMENSO_WEBHOOK_SECRET = SECRET
    settings.TELEGRAM_BOT_TOKEN = ""
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


def webhook(event, contract, **extra):
    """Ereignis im Format von Documenso (siehe Test vom 17.10.)."""
    return {"event": event, "payload": {"externalId": f"contract-{contract.pk}",
                                        "envelopeId": contract.signature_provider_id, **extra}}


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
    handle_documenso_webhook(webhook("DOCUMENT_COMPLETED", contract))
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
    handle_documenso_webhook(webhook("DOCUMENT_OPENED", contract))
    contract.refresh_from_db()
    assert contract.status == Contract.Status.PENDING
    handle_documenso_webhook(webhook("DOCUMENT_COMPLETED", contract))
    handle_documenso_webhook(webhook("DOCUMENT_REJECTED", contract))  # nach Unterschrift ohne Wirkung
    contract.refresh_from_db()
    assert contract.status == Contract.Status.SIGNED and contract.signed_at
    assert contract.events.filter(kind="documenso.DOCUMENT_REJECTED").exists()  # aber protokolliert


def test_webhook_declined(contract):
    send_contract(contract)
    handle_documenso_webhook(webhook("DOCUMENT_REJECTED", contract, rejectionReason="Zu teuer"))
    contract.refresh_from_db()
    assert contract.status == Contract.Status.DECLINED
    assert not contract.mandate.has_signed_contract and contract.decline_reason == "Zu teuer"


def test_webhook_unknown_submission(db):
    assert handle_documenso_webhook({"event": "DOCUMENT_COMPLETED", "payload": {"externalId": "contract-999"}}) is None


def test_fetch_signed_document(contract):
    send_contract(contract)
    fetch_signed_document(contract.pk, "https://sign.example/doc.pdf")
    contract.refresh_from_db()
    assert contract.document.read().startswith(b"%PDF")
    assert ContractEvent.objects.filter(contract=contract, kind="document_saved").exists()


def test_webhook_view_checks_secret(client, contract):
    send_contract(contract)
    body = json.dumps(webhook("DOCUMENT_COMPLETED", contract))
    url = "/clients/documenso/webhook/"
    assert client.post(url, body, content_type="application/json").status_code == 403
    assert client.post(url, body, content_type="application/json",
                       headers={"X-Documenso-Secret": "falsch"}).status_code == 403
    assert client.post(url, body, content_type="application/json",
                       headers={"X-Documenso-Secret": SECRET}).status_code == 200
    contract.refresh_from_db()
    assert contract.status == Contract.Status.SIGNED


def test_webhook_view_rejects_without_configured_secret(client, settings, contract):
    settings.DOCUMENSO_WEBHOOK_SECRET = ""
    resp = client.post("/clients/documenso/webhook/", "{}", content_type="application/json",
                       headers={"X-Documenso-Secret": ""})
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
