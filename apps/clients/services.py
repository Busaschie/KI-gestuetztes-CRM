"""Geschäftslogik – Views bleiben schlank.

Verträge (P1 Punkt 4): Versand über den Signaturdienst, Webhook-Verarbeitung, Ablage des unterschriebenen PDFs.
Die harte Sperre selbst sitzt in Mandate.has_signed_contract und OutboundMessage.save().
"""
import logging
from datetime import timedelta
from html import escape

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
        "Honorar": f"{float(fee.percent):g} % vom Jahresbruttogehalt",
        "Garantie": fee.guarantee_terms,
        "Abweichungen": contract.deviations,
        "Datum": timezone.localdate().strftime("%d.%m.%Y"),
    }


def notify(text: str, buttons=None) -> None:
    """Hinweis an Sandra per Telegram – darf nie den Vertragsablauf stören."""
    if not (settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_ALLOWED_CHAT_IDS):
        return
    try:
        from apps.bot.telegram import TelegramClient
        client = TelegramClient()
        for chat_id in settings.TELEGRAM_ALLOWED_CHAT_IDS:
            client.send_message(chat_id, text, buttons)
    except Exception as e:  # noqa: BLE001 – Benachrichtigung ist nur Zusatz
        log.warning("Telegram-Hinweis nicht gesendet: %s", e)


def _check_sendable(contract: Contract):
    if contract.needs_approval and not contract.approved_at:
        raise ContractError("Der Vertrag weicht von der Vorlage ab und muss erst freigegeben werden.")
    signer = contract.get_signer()
    if not signer or not signer.email:
        raise ContractError("Kein Unterzeichner mit E-Mail-Adresse (Unterzeichner oder Ansprechpartner des Auftrags).")
    if settings.CONTRACT_SOURCE == "template" and settings.SIGNATURE_PROVIDER != "fake" and not settings.DOCUSEAL_TEMPLATE_ID:
        raise ContractError("DOCUSEAL_TEMPLATE_ID fehlt in der .env.")
    if settings.CONTRACT_SOURCE == "pdf" and not settings.CONTRACTOR_NAME:
        raise ContractError("Daten der Auftragnehmerin fehlen (CONTRACTOR_NAME usw. in der .env).")
    return signer


def generate_contract_pdf(contract: Contract, for_signature: bool = False) -> bytes:
    """Vertrag als PDF erzeugen und als „Erzeugter Vertrag“ am Vertrag ablegen (Nachweis, was versendet wurde)."""
    from .contract_pdf import ContractLayoutError, build_contract_pdf

    try:
        pdf = build_contract_pdf(contract, for_signature=for_signature, signer_role=settings.DOCUSEAL_SIGNER_ROLE)
    except ContractLayoutError as e:
        raise ContractError(str(e)) from e
    if for_signature:
        stamp = timezone.localtime().strftime("%Y%m%d-%H%M")
        contract.draft_document.save(f"vertrag-{contract.pk}-{stamp}.pdf", ContentFile(pdf), save=True)
    return pdf


def schedule_contract(contract: Contract) -> Contract:
    """Versand vormerken: Nach CONTRACT_STOP_MINUTES geht der Vertrag raus, bis dahin kann Sandra stoppen."""
    if contract.status != Contract.Status.DRAFT:
        raise ContractError(f"Nur Entwürfe können versendet werden (Status: {contract.get_status_display()}).")
    signer = _check_sendable(contract)
    minutes = settings.CONTRACT_STOP_MINUTES
    if minutes <= 0:
        return send_contract(contract)
    contract.status = Contract.Status.SCHEDULED
    contract.scheduled_for = timezone.now() + timedelta(minutes=minutes)
    contract.save(update_fields=["status", "scheduled_for", "updated_at"])
    when = timezone.localtime(contract.scheduled_for)
    ContractEvent.objects.create(contract=contract, kind="scheduled", message=f"Versand geplant für {when:%d.%m.%Y %H:%M}")
    notify(
        f"📄 <b>Vertrag geht um {when:%H:%M} raus</b>\n{escape(str(contract.mandate))}\n"
        f"An: {escape(str(signer))} &lt;{escape(signer.email)}&gt;\n"
        f"Honorar: {float(contract.fee_model.percent):g} %" + (f"\nAbweichungen: {escape(contract.deviations)}" if contract.deviations else ""),
        [[("⛔ Stoppen", f"c{contract.pk}:stop"), ("📤 Jetzt senden", f"c{contract.pk}:now")]],
    )
    return contract


def stop_contract(contract: Contract) -> Contract:
    if contract.status != Contract.Status.SCHEDULED:
        raise ContractError(f"Nur geplante Verträge können gestoppt werden (Status: {contract.get_status_display()}).")
    contract.status, contract.scheduled_for = Contract.Status.DRAFT, None
    contract.save(update_fields=["status", "scheduled_for", "updated_at"])
    ContractEvent.objects.create(contract=contract, kind="stopped", message="Versand gestoppt")
    return contract


def send_due_contracts() -> int:
    """Läuft jede Minute (django-q): geplante Verträge versenden, deren Stopp-Fenster abgelaufen ist."""
    due = Contract.objects.filter(status=Contract.Status.SCHEDULED, scheduled_for__lte=timezone.now())
    sent = 0
    for contract in due:
        try:
            send_contract(contract)
            sent += 1
            notify(f"📤 Vertrag versendet: {escape(str(contract.mandate))}")
        except ContractError as e:
            contract.status, contract.scheduled_for = Contract.Status.DRAFT, None
            contract.save(update_fields=["status", "scheduled_for", "updated_at"])
            notify(f"⚠️ Vertrag <b>nicht</b> versendet: {escape(str(contract.mandate))}\n{escape(str(e))}\n"
                   "Zurück auf Entwurf – bitte im Admin prüfen.")
    return sent


def send_contract(contract: Contract) -> Contract:
    """Sofortiger Versand (nach Ablauf des Stopp-Fensters oder per „Jetzt senden“)."""
    if contract.status not in (Contract.Status.DRAFT, Contract.Status.SCHEDULED):
        raise ContractError(f"Nur Entwürfe können versendet werden (Status: {contract.get_status_display()}).")
    signer = _check_sendable(contract)

    try:
        provider = get_signature_provider()
        if settings.CONTRACT_SOURCE == "pdf":
            pdf = generate_contract_pdf(contract, for_signature=True)
            result = provider.create_submission_from_pdf(
                pdf=pdf, name=f"Vertrag {contract.mandate}"[:120], role=settings.DOCUSEAL_SIGNER_ROLE,
                signer_name=str(signer), signer_email=signer.email, external_id=f"contract-{contract.pk}",
            )
        else:
            result = provider.create_submission(
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
        contract.signature_submitter_id = result.submitter_id
        contract.scheduled_for = None
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


DOCUMENSO_EVENTS = {
    "DOCUMENT_OPENED": "opened", "DOCUMENT_SIGNED": "signed_by_one", "DOCUMENT_RECIPIENT_COMPLETED": "signed_by_one",
    "DOCUMENT_COMPLETED": "completed", "DOCUMENT_REJECTED": "declined", "DOCUMENT_CANCELLED": "cancelled",
}


def handle_documenso_webhook(payload: dict) -> Contract | None:
    """Documenso-Ereignis verarbeiten. Zuordnung über externalId („contract-<ID>“), sonst über die Envelope-ID.
    Idempotent; unterschrieben bleibt unterschrieben."""
    event = str(payload.get("event", ""))
    data = payload.get("payload") or {}
    contract = None
    external = str(data.get("externalId") or "")
    if external.startswith("contract-") and external[9:].isdigit():
        contract = Contract.objects.filter(pk=int(external[9:])).first()
    if not contract:
        ids = {str(data.get(k)) for k in ("envelopeId", "id") if data.get(k)}
        contract = Contract.objects.filter(signature_provider_id__in=ids).first() if ids else None
    if not contract:
        log.warning("Documenso-Webhook ohne passenden Vertrag: %s %s", event, external)
        return None

    ContractEvent.objects.create(contract=contract, kind=f"documenso.{event}", payload=payload)
    if contract.is_signed:
        return contract
    kind, now = DOCUMENSO_EVENTS.get(event), timezone.now()
    if kind == "completed":
        contract.status, contract.signed_at = Contract.Status.SIGNED, now
        contract.save()
        ref = f"envelope:{contract.signature_provider_id}"
        from django_q.tasks import async_task
        transaction.on_commit(lambda: async_task("apps.clients.services.fetch_signed_document", contract.pk, ref))
        notify(f"✅ Vertrag unterschrieben: {escape(str(contract.mandate))}")
    elif kind == "opened" and contract.status == Contract.Status.SENT:
        contract.status = Contract.Status.PENDING
        contract.save()
    elif kind == "declined":
        contract.status, contract.declined_at = Contract.Status.DECLINED, now
        contract.decline_reason = str(data.get("rejectionReason") or data.get("reason") or "")
        contract.save()
        notify(f"❌ Vertrag abgelehnt: {escape(str(contract.mandate))}")
    elif kind == "cancelled":
        contract.status = Contract.Status.CANCELLED
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


def send_contract_reminders(now=None) -> int:
    """Täglich (django-q): Erinnerung an den Kunden nach CONTRACT_REMINDER_DAYS (z. B. 3 und 7 Tage nach Versand).
    Automatisch erlaubt (Vertragsversand ist Ausnahme vom Freigabe-Grundsatz), wird protokolliert."""
    now = now or timezone.now()
    days = sorted(settings.CONTRACT_REMINDER_DAYS)
    waiting = Contract.objects.filter(
        status__in=[Contract.Status.SENT, Contract.Status.PENDING], sent_at__isnull=False, reminders_sent__lt=len(days),
    ).select_related("mandate", "signer", "mandate__contact_person")
    count = 0
    for contract in waiting:
        if now < contract.sent_at + timedelta(days=days[contract.reminders_sent]):
            continue
        try:
            get_signature_provider().remind(contract.signature_submitter_id, contract.signature_provider_id)
        except SignatureError as e:
            ContractEvent.objects.create(contract=contract, kind="reminder_failed", message=str(e))
            notify(f"⚠️ Vertragserinnerung fehlgeschlagen: {escape(str(contract.mandate))}\n{escape(str(e))}")
            continue
        signer = contract.get_signer()
        with transaction.atomic():
            contract.reminders_sent += 1
            contract.last_reminder_at = now
            contract.save(update_fields=["reminders_sent", "last_reminder_at", "updated_at"])
            ContractEvent.objects.create(contract=contract, kind="reminder",
                                         message=f"{contract.reminders_sent}. Erinnerung an {signer}")
            if signer:
                OutboundMessage.objects.create(
                    kind=OutboundMessage.Kind.CONTRACT_REMINDER, status=OutboundMessage.Status.SENT,
                    recipient=signer, mandate=contract.mandate, subject=f"Erinnerung Vertrag: {contract.mandate}",
                    body=f"{contract.reminders_sent}. Erinnerung über E-Signatur-Dienst", is_automatic=True, sent_at=now,
                )
        if contract.reminders_sent == len(days):
            notify(f"📄 Letzte automatische Erinnerung gesendet, Vertrag noch offen: {escape(str(contract.mandate))}\n"
                   "Bitte persönlich nachfassen.")
        count += 1
    return count
