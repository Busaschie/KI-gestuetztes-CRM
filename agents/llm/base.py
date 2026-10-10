"""Gemeinsame Schnittstelle für alle Sprachmodell-Anbieter (austauschbar über LLM_PROVIDER)."""
from abc import ABC, abstractmethod


class LLMError(RuntimeError):
    """Fehler beim Aufruf eines Sprachmodells – wird im Eingang als 'Fehler' sichtbar."""


class LLMProvider(ABC):
    name: str = "base"

    @abstractmethod
    def complete_json(self, system: str, user: str, schema: dict) -> dict:
        """Gibt eine Antwort als JSON-Objekt zurück, das zum Schema passen soll."""


class OCRProvider(ABC):
    @abstractmethod
    def ocr_pdf(self, data: bytes) -> str:
        """Liest den Text eines gescannten PDFs aus."""
