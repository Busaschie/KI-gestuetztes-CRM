"""Sprache → Text, austauschbar über TRANSCRIBE_PROVIDER (.env): mistral | whisper | fake.

- mistral: Voxtral über die Mistral-API (EU) – für den Betrieb.
- whisper: faster-whisper lokal auf der CPU – für die Entwicklung, keine Daten verlassen den Rechner.
  Installation: pip install faster-whisper (Modell wird beim ersten Aufruf geladen, „small“ ca. 500 MB).
- fake: feste Antwort für Tests.
"""
import io
import logging

import httpx
from django.conf import settings

from .base import LLMError

log = logging.getLogger(__name__)


class Transcriber:
    def transcribe(self, data: bytes, filename: str, hints: list[str] | None = None) -> str:
        """hints: bekannte Namen (Personen), die die Erkennung bevorzugen soll – wo der Anbieter das unterstützt."""
        raise NotImplementedError


class MistralTranscriber(Transcriber):
    URL = "https://api.mistral.ai/v1/audio/transcriptions"

    def __init__(self, api_key: str, model: str, language: str = "", timeout: float = 120):
        if not api_key:
            raise LLMError("MISTRAL_API_KEY fehlt in der .env (für TRANSCRIBE_PROVIDER=mistral)")
        self.api_key, self.model, self.language, self.timeout = api_key, model, language, timeout

    def transcribe(self, data, filename, hints=None):
        form = {"model": self.model}
        if self.language:
            form["language"] = self.language
        try:
            r = httpx.post(self.URL, headers={"Authorization": f"Bearer {self.api_key}"}, data=form,
                           files={"file": (filename, data)}, timeout=self.timeout)
        except httpx.HTTPError as e:
            raise LLMError(f"Mistral-Transkription nicht erreichbar: {type(e).__name__}") from e
        if r.status_code != 200:
            raise LLMError(f"Mistral-Transkription {r.status_code}: {r.text[:300]}")
        return (r.json().get("text") or "").strip()


_whisper_model = None  # einmal laden, dann wiederverwenden (Laden dauert)


class WhisperTranscriber(Transcriber):
    def __init__(self, model: str, language: str = ""):
        self.model_name, self.language = model, language or None

    def transcribe(self, data, filename, hints=None):
        global _whisper_model
        try:
            from faster_whisper import WhisperModel
        except ImportError as e:
            raise LLMError("faster-whisper ist nicht installiert: pip install faster-whisper") from e
        if _whisper_model is None:
            log.warning("Lade Whisper-Modell „%s“ …", self.model_name)
            _whisper_model = WhisperModel(self.model_name, device="cpu", compute_type="int8")
        hotwords = ", ".join(hints) if hints else None
        segments, _ = _whisper_model.transcribe(decode_audio(data), language=self.language, vad_filter=True,
                                                hotwords=hotwords)
        return " ".join(s.text.strip() for s in segments).strip()


def decode_audio(data: bytes, rate: int = 16000):
    """Audio (z. B. Telegram-.oga/Opus) → Mono-Float-Array mit 16 kHz, wie Whisper es erwartet.
    Eigene Umsetzung statt faster_whisper.decode_audio: diese ruft av.open mit einem Parameter auf,
    den neuere PyAV-Versionen (ab 15/16) nicht mehr kennen."""
    import av
    import numpy as np

    chunks = []
    try:
        with av.open(io.BytesIO(data), mode="r") as container:
            resampler = av.AudioResampler(format="s16", layout="mono", rate=rate)
            for frame in container.decode(audio=0):
                chunks += [f.to_ndarray() for f in resampler.resample(frame)]
            chunks += [f.to_ndarray() for f in resampler.resample(None)]  # Rest ausgeben
    except av.error.FFmpegError as e:
        raise LLMError(f"Audiodatei nicht lesbar: {e}") from e
    if not chunks:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(chunks, axis=1).flatten().astype(np.float32) / 32768.0


class FakeTranscriber(Transcriber):
    text: str = ""
    last_hints: list[str] | None = None

    def transcribe(self, data, filename, hints=None):
        FakeTranscriber.last_hints = hints
        return self.text


def get_transcriber() -> Transcriber:
    provider = settings.TRANSCRIBE_PROVIDER
    if provider == "mistral":
        return MistralTranscriber(settings.MISTRAL_API_KEY, settings.MISTRAL_TRANSCRIBE_MODEL, settings.TRANSCRIBE_LANGUAGE)
    if provider == "whisper":
        return WhisperTranscriber(settings.WHISPER_MODEL, settings.TRANSCRIBE_LANGUAGE)
    if provider == "fake":
        return FakeTranscriber()
    raise LLMError(f"Unbekannter TRANSCRIBE_PROVIDER: {provider}")


def name_hints(limit: int | None = None) -> list[str]:
    """Namen der zuletzt bearbeiteten Personen – helfen Whisper bei seltenen Namen (z. B. Schönweitz)."""
    from apps.contacts.models import Person

    limit = settings.TRANSCRIBE_NAME_HINTS if limit is None else limit
    if limit <= 0:
        return []
    names = (str(p) for p in Person.objects.order_by("-updated_at").only("first_name", "last_name")[:limit])
    return list(dict.fromkeys(n for n in names if n))
