"""Simuliert ein Documenso-Ereignis für einen Vertrag – zum Testen ohne öffentlich erreichbaren Server.

Beispiel: python manage.py contract_webhook 3 DOCUMENT_COMPLETED
"""
from django.core.management.base import BaseCommand, CommandError

from apps.clients.models import Contract
from apps.clients.services import DOCUMENSO_EVENTS, fetch_signed_document, handle_documenso_webhook


class Command(BaseCommand):
    help = "Simuliert ein Documenso-Webhook-Ereignis für einen versendeten Vertrag"

    def add_arguments(self, parser):
        parser.add_argument("contract_id", type=int)
        parser.add_argument("event", choices=sorted(DOCUMENSO_EVENTS))
        parser.add_argument("--reason", default="Test-Ablehnung", help="Ablehnungsgrund bei DOCUMENT_REJECTED")

    def handle(self, contract_id, event, reason, **opts):
        contract = Contract.objects.filter(pk=contract_id).first()
        if not contract or not contract.signature_provider_id:
            raise CommandError("Vertrag nicht gefunden oder noch nicht versendet.")
        handle_documenso_webhook({"event": event, "payload": {
            "externalId": f"contract-{contract.pk}", "envelopeId": contract.signature_provider_id,
            "rejectionReason": reason,
        }})
        contract.refresh_from_db()
        if contract.is_signed and not contract.document and contract.signature_provider_id.startswith("fake-"):
            fetch_signed_document(contract.pk, "fake")  # Fake: direkt, ohne Warteschlange
        self.stdout.write(self.style.SUCCESS(f"{contract} – Status: {contract.get_status_display()}"))
