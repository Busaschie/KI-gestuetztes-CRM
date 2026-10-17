"""Documenso-Anbindung (API v2 Envelopes) – mit nachgebildeten HTTP-Antworten, ohne echten Server."""
import json
from decimal import Decimal

import httpx
import pytest

from apps.clients.models import Contract, FeeModel
from apps.clients.services import handle_documenso_webhook, send_contract
from apps.contacts.models import Company, Person
from apps.jobs.models import Mandate


@pytest.fixture(autouse=True)
def cfg(settings, tmp_path):
    settings.SIGNATURE_PROVIDER = "documenso"
    settings.DOCUMENSO_API_URL = "http://documenso.test/api/v2"
    settings.DOCUMENSO_API_KEY = "api_test"
    settings.DOCUMENSO_WEBHOOK_SECRET = "geheim"
    settings.MEDIA_ROOT = str(tmp_path)
    settings.TELEGRAM_BOT_TOKEN = ""


@pytest.fixture
def contract(db):
    company = Company.objects.create(name="Muster AG", country="AT")
    contact = Person.objects.create(first_name="Karl", last_name="Kunde", email="karl@muster.example")
    mandate = Mandate.objects.create(company=company, contact_person=contact, title="CFO")
    fee = FeeModel.objects.create(name="E", percent=Decimal("20"))
    return Contract.objects.create(mandate=mandate, company=company, fee_model=fee)


def test_send_creates_and_distributes_envelope(contract, monkeypatch):
    calls = []

    def fake_request(method, url, headers=None, timeout=None, **kw):
        calls.append((method, url, kw))
        req = httpx.Request(method, url)
        if url.endswith("/envelope/create"):
            payload = json.loads(kw["data"]["payload"])
            assert payload["externalId"] == f"contract-{contract.pk}"
            assert payload["recipients"][0]["email"] == "karl@muster.example"
            name, pdf, mime = kw["files"]["files"]
            assert pdf.startswith(b"%PDF") and mime == "application/pdf"
            return httpx.Response(200, json={"id": "envelope_123"}, request=req)
        if url.endswith("/envelope/distribute"):
            assert kw["json"] == {"envelopeId": "envelope_123"}
            return httpx.Response(200, json={"success": True, "id": "envelope_123", "recipients": [
                {"id": 7, "signingUrl": "http://documenso.test/sign/abc"}]}, request=req)
        raise AssertionError(url)

    monkeypatch.setattr("apps.clients.signature.documenso.httpx.request", fake_request)
    send_contract(contract)
    contract.refresh_from_db()
    assert contract.status == Contract.Status.SENT
    assert contract.signature_provider_id == "envelope_123" and contract.signature_submitter_id == "7"
    assert contract.signing_url.endswith("/sign/abc")


def test_pdf_contains_documenso_placeholder(contract):
    import io

    from pypdf import PdfReader

    from apps.clients.contract_pdf import build_contract_pdf

    text = PdfReader(io.BytesIO(build_contract_pdf(contract, for_signature=True))).pages[0].extract_text()
    assert "{{signature, r1}}" in text


def test_webhook_completed_by_external_id(contract):
    Contract.objects.filter(pk=contract.pk).update(status=Contract.Status.SENT, signature_provider_id="envelope_123")
    handle_documenso_webhook({"event": "DOCUMENT_OPENED", "payload": {"externalId": f"contract-{contract.pk}"}})
    assert Contract.objects.get(pk=contract.pk).status == Contract.Status.PENDING
    handle_documenso_webhook({"event": "DOCUMENT_COMPLETED", "payload": {"externalId": f"contract-{contract.pk}"}})
    handle_documenso_webhook({"event": "DOCUMENT_REJECTED", "payload": {"id": "envelope_123"}})
    c = Contract.objects.get(pk=contract.pk)
    assert c.status == Contract.Status.SIGNED and c.signed_at
    assert c.events.filter(kind="documenso.DOCUMENT_REJECTED").exists()


def test_webhook_view_secret(client, contract):
    url = "/clients/documenso/webhook/"
    body = json.dumps({"event": "DOCUMENT_COMPLETED", "payload": {"externalId": f"contract-{contract.pk}"}})
    assert client.post(url, body, content_type="application/json").status_code == 403
    assert client.post(url, body, content_type="application/json",
                       headers={"X-Documenso-Secret": "geheim"}).status_code == 200


def test_real_payload_shape(contract):
    """Aufbau wie im echten Test vom 17.10. (gekürzt): event + payload.externalId/envelopeId."""
    Contract.objects.filter(pk=contract.pk).update(status=Contract.Status.SENT,
                                                   signature_provider_id="envelope_dthsnsnmabsnbsuv")
    handle_documenso_webhook({
        "event": "DOCUMENT_COMPLETED",
        "payload": {"id": 1, "status": "COMPLETED", "envelopeId": "envelope_dthsnsnmabsnbsuv",
                    "externalId": f"contract-{contract.pk}", "completedAt": "2026-10-17T12:26:46.947Z"},
        "createdAt": "2026-10-17T12:26:47.060Z",
    })
    assert Contract.objects.get(pk=contract.pk).status == Contract.Status.SIGNED


def test_reminder_redistributes(contract, monkeypatch, settings):
    from datetime import timedelta

    from django.utils import timezone

    from apps.clients.services import send_contract_reminders

    settings.CONTRACT_REMINDER_DAYS = [3]
    Contract.objects.filter(pk=contract.pk).update(
        status=Contract.Status.SENT, signature_provider_id="envelope_123", signature_submitter_id="7",
        sent_at=timezone.now() - timedelta(days=4))
    seen = {}

    def fake_request(method, url, headers=None, timeout=None, **kw):
        seen.update(url=url, json=kw.get("json"))
        return httpx.Response(200, json={"success": True, "id": "envelope_123", "recipients": []},
                              request=httpx.Request(method, url))

    monkeypatch.setattr("apps.clients.signature.documenso.httpx.request", fake_request)
    assert send_contract_reminders() == 1
    assert seen["url"].endswith("/envelope/redistribute")
    assert seen["json"] == {"envelopeId": "envelope_123", "recipients": [7]}
