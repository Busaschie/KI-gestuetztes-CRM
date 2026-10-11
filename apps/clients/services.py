"""Geschäftslogik – Views bleiben schlank.

Verträge (P1 Punkt 4): Versand über den Signaturdienst, Webhook-Verarbeitung, Ablage des unterschriebenen PDFs.
Die harte Sperre selbst sitzt in Mandate.has_signed_contract und OutboundMessage.save().
"""
import logging

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from apps.communications.models import OutboundMessage

from .models import Contract, ContractEvent
from .signature import SignatureError, get_signature_provider

log = logging.getLogger(__name__)


class ContractError(Exception):
    """Vertrag kann (noch) nicht versendet werden – Text ist für Sandra lesbar."""


def contract_values(contract: Contract) -> dict:
    """Vorbefüllte Felder der DocuSeal-Vorlage. Feldnamen müssen in der Vorlage genau so heißen."""
    fee = contract.fee_model
    return {
        "Kunde": contract.company.name,
        "Position": contract.mandate.title,
        "Einsatzort": contract.mandate.location,
        "Honorar": f"{fee.percent:g} % vom Jahresbruttogehalt",
        "Garantie": fee.guarantee_terms,
        "Abweichungen": contract.deviations,
        "Datum": timezone.localdate().strftime("%d.%m.%Y"),
    }


def send_contract(contract: Contract) -> Contract:
    if contract.status != Contract.Status.DRAFT:
        raise ContractError(f"Nur Entwürfe können versendet werden (Status: {contract.get_status_display()}).")
    if contract.needs_approval and not contract.approved_at:
        raise ContractError("Der Vertrag weicht von der Vorlage ab und muss erst freigegeben werden.")
    signer = contract.get_signer()
    if not signer or not signer.email:
        raise ContractError("Kein Unterzeichner mit E-Mail-Adresse (Unterzeichner oder Ansprechpartner des Auftrags).")
    if settings.SIGNATURE_PROVIDER != "fake" and not settings.DOCUSEAL_TEMPLATE_ID:
        raise ContractError("DOCUSEAL_TEMPLATE_ID fehlt in der .env.")

    try:
        result = get_signature_provider().create_submission(
            template_id=settings.DOCUSEAL_TEMPLATE_ID or "0",
            role=settings.DOCUSEAL_SIGNER_ROLE,
            signer_name=str(signer),
            signer_email=signer.email,
            values=contract_values(contract),
            external_id=f"contract-{contract.pk}",
        )
    except SignatureError as e:
        ContractEvent.objects.create(contract=contract, kind="send_failed", message=str(e))
        raise ContractError(str(e)) from e

    now = timezone.now()
    with transaction.atomic():
        contract.signature_provider_id = result.submission_id
        contract.signing_url = result.signing_url
        contract.status = Contract.Status.SENT
        contract.sent_at = now
        contract.save()
        ContractEvent.objects.create(
            contract=contract, kind="sent", message=f"An {signer} <{signer.email}> versendet",
            payload={"submission_id": result.submission_id},
        )
        # Protokoll aller ausgehenden Nachrichten (Vertragsversand ist eine erlaubte automatische Ausnahme)
        OutboundMessage.objects.create(
            kind=OutboundMessage.Kind.CONTRACT, status=OutboundMessage.Status.SENT, recipient=signer,
            mandate=contract.mandate, subject=f"Vertrag: {contract.mandate}",
            body=f"Versand über E-Signatur-Dienst ({settings.SIGNATURE_PROVIDER}), ID {result.submission_id}",
            is_automatic=True, sent_at=now,
        )
    return contract


def _submission_id(event_type: str, data: dict) -> str:
    if event_type.startswith("submission."):
        return str(data.get("id", ""))
    sub = data.get("submission") or {}
    return str(sub.get("id") or data.get("submission_id") or "")


def _document_url(data: dict) -> str:
    sub = data.get("submission") or {}
    docs = data.get("documents") or []
    return (sub.get("combined_document_url") or data.get("combined_document_url")
            or (docs[0].get("url") if docs else "") or "")


def handle_webhook(payload: dict) -> Contract | None:
    """Verarbeitet ein DocuSeal-Ereignis. Idempotent: Wiederholungen ändern nichts."""
    event_type = str(payload.get("event_type", ""))
    data = payload.get("data") or {}
    submission_id = _submission_id(event_type, data)
    contract = Contract.objects.filter(signature_provider_id=submission_id).first() if submission_id else None
    if not contract:
        log.warning("DocuSeal-Webhook ohne passenden Vertrag: %s %s", event_type, submission_id)
        return None

    ContractEvent.objects.create(contract=contract, kind=event_type, payload=payload)
    if contract.is_signed:
        return contract  # unterschrieben bleibt unterschrieben

    now = timezone.now()
    if event_type in ("form.completed", "submission.completed"):
        contract.status = Contract.Status.SIGNED
        contract.signed_at = now
        contract.save()
        if url := _document_url(data):
            from django_q.tasks import async_task
            transaction.on_commit(lambda: async_task("apps.clients.services.fetch_signed_document", contract.pk, url))
    elif event_type in ("form.viewed", "form.started") and contract.status == Contract.Status.SENT:
        contract.status = Contract.Status.PENDING
        contract.save()
    elif event_type == "form.declined":
        contract.status = Contract.Status.DECLINED
        contract.declined_at = now
        contract.decline_reason = str(data.get("decline_reason") or "")
        contract.save()
    elif event_type == "submission.expired":
        contract.status = Contract.Status.EXPIRED
        contract.save()
    return contract


def fetch_signed_document(contract_id: int, url: str) -> None:
    """Lädt das unterschriebene PDF in die eigene Ablage (Links beim Dienst laufen ab)."""
    contract = Contract.objects.get(pk=contract_id)
    try:
        data = get_signature_provider().download(url)
    except SignatureError as e:
        ContractEvent.objects.create(contract=contract, kind="download_failed", message=str(e))
        raise
    contract.document.save(f"vertrag-{contract.pk}-unterschrieben.pdf", ContentFile(data), save=True)
    ContractEvent.objects.create(contract=contract, kind="document_saved", message=contract.document.name)
