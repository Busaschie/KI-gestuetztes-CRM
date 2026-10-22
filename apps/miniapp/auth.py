"""Anmeldung der Telegram Mini App über initData (B-032).

Telegram übergibt beim Öffnen signierte Nutzerdaten (`initData`). Die Seite schickt sie bei JEDER Anfrage im Header
X-Telegram-Init-Data mit; der Server prüft die HMAC-Signatur mit dem Bot-Token und lässt nur freigeschaltete
Chat-IDs zu. Kein Cookie, keine Sitzung, kein CSRF-Angriffsweg (ein fremder Browser hat die Signatur nicht).
Doku: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""
import hashlib
import hmac
import json
import time
from functools import wraps
from urllib.parse import parse_qsl

from django.conf import settings
from django.http import HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt

HEADER = "HTTP_X_TELEGRAM_INIT_DATA"


class InitDataError(ValueError):
    pass


def check_init_data(init_data: str, bot_token: str, max_age: int, now: float | None = None) -> dict:
    """Prüft Signatur und Alter; gibt den Telegram-Nutzer (dict mit id, first_name, …) zurück."""
    if not init_data or not bot_token:
        raise InitDataError("keine Anmeldedaten")
    data = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=False))
    received = data.pop("hash", "")
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if not received or not hmac.compare_digest(expected, received):
        raise InitDataError("Signatur ungültig")
    try:
        auth_date = int(data.get("auth_date", "0"))
        user = json.loads(data.get("user", "{}"))
    except (ValueError, TypeError) as e:
        raise InitDataError("Daten unlesbar") from e
    if (now or time.time()) - auth_date > max_age:
        raise InitDataError("Anmeldung abgelaufen – Mini App neu öffnen")
    if not user.get("id"):
        raise InitDataError("kein Nutzer")
    return user


def tg_required(view):
    """Nur für freigeschaltete Telegram-Nutzer; setzt request.tg_user."""
    @csrf_exempt  # Schutz kommt über die Signatur im Header, nicht über Cookies
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        try:
            user = check_init_data(request.META.get(HEADER, ""), settings.TELEGRAM_BOT_TOKEN,
                                   settings.MINIAPP_MAX_AGE_SECONDS)
        except InitDataError as e:
            return HttpResponseForbidden(f'<p class="error">Kein Zugriff: {e}</p>')
        if int(user["id"]) not in settings.TELEGRAM_ALLOWED_CHAT_IDS:
            return HttpResponseForbidden('<p class="error">Kein Zugriff: nicht freigeschaltet.</p>')
        request.tg_user = user
        return view(request, *args, **kwargs)
    return wrapper
