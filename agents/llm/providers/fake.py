"""Fake-Anbieter für Tests: gibt vorgegebene Antworten zurück, ohne Netz."""
from agents.llm.base import LLMProvider, OCRProvider


class FakeProvider(LLMProvider, OCRProvider):
    name = "fake"
    response: dict = {}
    ocr_text: str = ""

    def complete_json(self, system: str, user: str, schema: dict) -> dict:
        return dict(self.response)

    def ocr_pdf(self, data: bytes) -> str:
        return self.ocr_text
