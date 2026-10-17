import hmac
import json
import logging

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .services import handle_documenso_webhook

log = logging.getLogger(__name__)


@staff_member_required
def contract_preview(request, pk):
    """PDF-Vorschau des Vertrags (ohne Speichern, ohne Unterschriftsfeld)."""
    from django.shortcuts import get_object_or_404

    from .contract_pdf import ContractLayoutError, build_contract_pdf
    from .models import Contract

    contract = get_object_or_404(Contract.objects.select_related("mandate", "company", "fee_model"), pk=pk)
    try:
        pdf = build_contract_pdf(contract)
    except ContractLayoutError as e:
        return HttpResponse(f"Vertrag kann nicht erzeugt werden: {e}", status=400, content_type="text/plain; charset=utf-8")
    resp = HttpResponse(pdf, content_type="application/pdf")
    resp["Content-Disposition"] = f'inline; filename="vertrag-{contract.pk}-vorschau.pdf"'
    return resp


@csrf_exempt
@require_POST
def documenso_webhook(request):
    """Documenso schickt das Geheimnis im Header X-Documenso-Secret (Klartext, kein HMAC)."""
    secret = settings.DOCUMENSO_WEBHOOK_SECRET
    given = request.headers.get("X-Documenso-Secret", "")
    if not secret or not hmac.compare_digest(given.encode(), secret.encode()):
        log.warning("Documenso-Webhook mit falschem oder fehlendem Geheimnis abgelehnt")
        return HttpResponseForbidden()
    try:
        payload = json.loads(request.body)
    except ValueError:
        return HttpResponseBadRequest("Kein JSON")
    if not isinstance(payload, dict):
        return HttpResponseBadRequest("Kein Objekt")
    handle_documenso_webhook(payload)
    return HttpResponse("ok")
