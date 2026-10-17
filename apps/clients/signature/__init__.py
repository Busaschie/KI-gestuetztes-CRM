"""E-Signatur austauschbar über SIGNATURE_PROVIDER (.env): documenso | fake.

DocuSeal wurde am 17.10.2026 entfernt (eigenes PDF nur mit Pro) – letzter Stand im Git-Verlauf."""
from django.conf import settings

from .base import SignatureError, SignatureProvider, SubmissionResult

__all__ = ["SignatureError", "SignatureProvider", "SubmissionResult", "get_signature_provider"]


def get_signature_provider() -> SignatureProvider:
    provider = settings.SIGNATURE_PROVIDER
    if provider == "documenso":
        from .documenso import DocumensoProvider
        return DocumensoProvider(settings.DOCUMENSO_API_URL, settings.DOCUMENSO_API_KEY)
    if provider == "fake":
        from .fake import FakeSignatureProvider
        return FakeSignatureProvider()
    raise SignatureError(f"Unbekannter SIGNATURE_PROVIDER: {provider}")
