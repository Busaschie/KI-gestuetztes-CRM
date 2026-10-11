import hmac
import json
import logging

from django.conf import settings
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .services import handle_webhook

log = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def docuseal_webhook(request):
    secret = settings.DOCUSEAL_WEBHOOK_SECRET
    given = request.headers.get(settings.DOCUSEAL_WEBHOOK_HEADER, "")
    if not secret or not hmac.compare_digest(given.encode(), secret.encode()):
        log.warning("DocuSeal-Webhook mit falschem oder fehlendem Geheimnis abgelehnt")
        return HttpResponseForbidden()
    try:
        payload = json.loads(request.body)
    except ValueError:
        return HttpResponseBadRequest("Kein JSON")
    if not isinstance(payload, dict):
        return HttpResponseBadRequest("Kein Objekt")
    handle_webhook(payload)
    return HttpResponse("ok")  # auch bei unbekanntem Vertrag 200 – sonst wiederholt DocuSeal 48 h lang
