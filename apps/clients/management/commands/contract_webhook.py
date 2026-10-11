"""Simuliert ein DocuSeal-Ereignis für einen Vertrag – zum Testen ohne öffentlich erreichbaren Server.

Beispiel: python manage.py contract_webhook 3 form.completed
"""
from django.core.management.base import BaseCommand, CommandError

from apps.clients.models import Contract
from apps.clients.services import fetch_signed_document, handle_webhook

EVENTS = ["form.viewed", "form.started", "form.completed", "form.declined", "submission.completed", "submission.expired"]


class Command(BaseCommand):
    help = "Simuliert ein DocuSeal-Webhook-Ereignis für einen versendeten Vertrag"

    def add_arguments(self, parser):
        parser.add_argument("contract_id", type=int)
        parser.add_argument("event", choices=EVENTS)
        parser.add_argument("--reason", default="Test-Ablehnung", help="Ablehnungsgrund bei form.declined")

    def handle(self, contract_id, event, reason, **opts):
        contract = Contract.objects.filter(pk=contract_id).first()
        if not contract or not contract.signature_provider_id:
            raise CommandError("Vertrag nicht gefunden oder noch nicht versendet.")
        sid = contract.signature_provider_id
        data = {"id": sid} if event.startswith("submission.") else {"submission": {"id": sid}, "decline_reason": reason}
        handle_webhook({"event_type": event, "timestamp": "simuliert", "data": data})
        contract.refresh_from_db()
        if contract.is_signed and not contract.document and sid.startswith("fake-"):
            fetch_signed_document(contract.pk, "https://sign.example/fake.pdf")  # direkt, ohne Warteschlange
        self.stdout.write(self.style.SUCCESS(f"{contract} – Status: {contract.get_status_display()}"))
