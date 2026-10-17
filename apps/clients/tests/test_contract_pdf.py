"""Vertrags-PDF im Layout der Vorlage (16.10.)."""
import io
from decimal import Decimal

import pytest
from pypdf import PdfReader

from apps.clients.contract_pdf import build_contract_pdf, contract_context
from apps.clients.models import Contract, FeeModel
from apps.clients.services import send_contract
from apps.clients.signature.fake import FakeSignatureProvider
from apps.contacts.models import Company, Person
from apps.jobs.models import Mandate


@pytest.fixture(autouse=True)
def cfg(settings, tmp_path, monkeypatch):
    settings.SIGNATURE_PROVIDER = "fake"
    settings.CONTRACT_SOURCE = "pdf"
    settings.CONTRACTOR_NAME = "Sandra Test pfa"
    settings.CONTRACTOR_ADDRESS = "Teststraße 1, RO-123 Ort|Rumänien"
    settings.CONTRACTOR_SIGNER = "Sandra Test"
    settings.MEDIA_ROOT = str(tmp_path)
    settings.TELEGRAM_BOT_TOKEN = ""
    monkeypatch.setattr(FakeSignatureProvider, "pdf_calls", [])


@pytest.fixture
def contract(db):
    company = Company.objects.create(name="Wech Geflügel GmbH", street="Kollegg 8a", postal_code="9433",
                                     city="St. Andrä", country="AT")
    contact = Person.objects.create(first_name="Max", last_name="Muster", email="max@wech.example")
    mandate = Mandate.objects.create(company=company, contact_person=contact, title="Senior Controller",
                                     employment_type="Festanstellung")
    fee = FeeModel.objects.create(name="Einzel 15", percent=Decimal("15.00"), guarantee_months=6)
    return Contract.objects.create(mandate=mandate, company=company, fee_model=fee)


def text_of(pdf: bytes) -> str:
    return " ".join(PdfReader(io.BytesIO(pdf)).pages[0].extract_text().split())


def test_context_values(contract):
    c = contract_context(contract)
    assert c["client_address"] == ["Kollegg 8a", "9433 St. Andrä", "Österreich"]
    assert c["percent"] == "15 %" and c["guarantee_months"] == 6 and c["employment_type"] == "Festanstellung"


def test_pdf_contains_values(contract):
    pdf = build_contract_pdf(contract)
    assert pdf.startswith(b"%PDF") and len(PdfReader(io.BytesIO(pdf)).pages) == 1
    text = text_of(pdf)
    for expected in ("Wech Geflügel GmbH", "Senior Controller", "Festanstellung", "15 %", "6 Monaten",
                     "Kollegg 8a", "Sandra Test pfa", "österreichisches Recht"):
        assert expected in text, expected
    assert "{{" not in text  # ohne Unterschrifts-Tag


def test_signature_tag_only_for_signing(contract):
    assert "{{Unterschrift;role=First Party;type=signature}}" in text_of(build_contract_pdf(contract, True))


def test_long_deviations_raise_clear_error(contract):
    from apps.clients.contract_pdf import ContractLayoutError

    contract.deviations = "Sehr lange Sonderklausel. " * 200
    with pytest.raises(ContractLayoutError):
        build_contract_pdf(contract)


def test_send_uses_generated_pdf(contract):
    send_contract(contract)
    contract.refresh_from_db()
    assert contract.status == Contract.Status.SENT and contract.draft_document
    call = FakeSignatureProvider.pdf_calls[-1]
    assert call["signer_email"] == "max@wech.example" and call["pdf"].startswith(b"%PDF")


def test_preview_view_staff_only(client, contract, django_user_model):
    url = f"/clients/contracts/{contract.pk}/vorschau.pdf"
    assert client.get(url).status_code == 302
    client.force_login(django_user_model.objects.create_superuser("a", "a@x.example", "pw"))
    resp = client.get(url)
    assert resp.status_code == 200 and resp["Content-Type"] == "application/pdf"
