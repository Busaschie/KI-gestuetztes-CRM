"""Wählt den Sprachmodell-Anbieter anhand von LLM_PROVIDER (.env): mistral | ollama | fake."""
from django.conf import settings

from .base import LLMError, LLMProvider, OCRProvider


def get_llm() -> LLMProvider:
    provider = settings.LLM_PROVIDER
    if provider == "mistral":
        from .providers.mistral import MistralProvider
        return MistralProvider(
            settings.MISTRAL_API_KEY, settings.MISTRAL_MODEL, settings.MISTRAL_OCR_MODEL,
            max_tokens=settings.MISTRAL_MAX_TOKENS,
        )
    if provider == "ollama":
        from .providers.ollama import OllamaProvider
        return OllamaProvider(
            settings.OLLAMA_URL, settings.OLLAMA_MODEL, timeout=settings.OLLAMA_TIMEOUT, num_ctx=settings.OLLAMA_NUM_CTX,
            num_predict=settings.OLLAMA_NUM_PREDICT,
        )
    if provider == "fake":
        from .providers.fake import FakeProvider
        return FakeProvider()
    raise LLMError(f"Unbekannter LLM_PROVIDER: {provider}")


def get_ocr() -> OCRProvider | None:
    """OCR für gescannte PDFs – derzeit nur über Mistral (EU). Ohne Mistral-Schlüssel: None."""
    if settings.LLM_PROVIDER == "fake":
        from .providers.fake import FakeProvider
        return FakeProvider()
    if settings.MISTRAL_API_KEY:
        from .providers.mistral import MistralProvider
        return MistralProvider(
            settings.MISTRAL_API_KEY, settings.MISTRAL_MODEL, settings.MISTRAL_OCR_MODEL,
            max_tokens=settings.MISTRAL_MAX_TOKENS,
        )
    return None
