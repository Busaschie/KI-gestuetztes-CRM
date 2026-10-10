"""Mistral (EU-Hosting). Standard für den Betrieb."""
import base64
import json
import time

import httpx

from agents.llm.base import LLMError, LLMProvider, OCRProvider

API = "https://api.mistral.ai/v1"


class MistralProvider(LLMProvider, OCRProvider):
    name = "mistral"

    RETRY_WAITS = (5, 20, 60)  # Sekunden – falls Mistral keine Wartezeit vorgibt

    def __init__(self, api_key: str, model: str, ocr_model: str, timeout: float = 120, max_tokens: int = 4096,
                 transport=None, sleep=time.sleep):
        if not api_key:
            raise LLMError("MISTRAL_API_KEY fehlt in der .env")
        self.model = model
        self.ocr_model = ocr_model
        self._sleep = sleep
        self.max_tokens = max_tokens  # Obergrenze der Antwort – zählt sonst voll gegen das Tokens-pro-Minute-Limit
        self.client = httpx.Client(
            base_url=API, timeout=timeout, headers={"Authorization": f"Bearer {api_key}"}, transport=transport
        )

    def complete_json(self, system: str, user: str, schema: dict) -> dict:
        payload = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": self.max_tokens,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": f"{system}\n\nAntworte ausschließlich mit JSON nach diesem Schema:\n{json.dumps(schema, ensure_ascii=False)}"},
                {"role": "user", "content": user},
            ],
        }
        r = self._post("/chat/completions", payload)
        if r.status_code != 200:
            raise LLMError(f"Mistral {r.status_code}: {r.text[:300]}")
        content = r.json()["choices"][0]["message"]["content"]
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            raise LLMError(f"Mistral lieferte kein gültiges JSON: {e}") from e

    def ocr_pdf(self, data: bytes) -> str:
        b64 = base64.b64encode(data).decode()
        payload = {
            "model": self.ocr_model,
            "document": {"type": "document_url", "document_url": f"data:application/pdf;base64,{b64}"},
        }
        r = self._post("/ocr", payload)
        if r.status_code != 200:
            raise LLMError(f"Mistral OCR {r.status_code}: {r.text[:300]}")
        return "\n\n".join(p.get("markdown", "") for p in r.json().get("pages", []))

    def _post(self, path, payload):
        """POST mit Wiederholung bei Ratenlimit (429) oder kurzzeitiger Überlastung (502/503)."""
        for attempt in range(len(self.RETRY_WAITS) + 1):
            try:
                r = self.client.post(path, json=payload)
            except httpx.TimeoutException as e:
                raise LLMError("Mistral hat nicht rechtzeitig geantwortet") from e
            except httpx.HTTPError as e:
                raise LLMError(f"Mistral-Verbindungsfehler: {e}") from e
            if r.status_code not in (429, 502, 503) or attempt == len(self.RETRY_WAITS):
                if r.status_code == 429:
                    raise LLMError(
                        "Mistral: Ratenlimit überschritten (429) – Limits unter admin.mistral.ai/plateforme/limits prüfen, "
                        "im Free-Modus ggf. Pay-as-you-go aktivieren"
                    )
                return r
            self._sleep(self._wait_seconds(r, attempt))
        return r

    def _wait_seconds(self, r, attempt) -> float:
        try:
            return min(float(r.headers.get("retry-after", "")), 120)
        except ValueError:
            return self.RETRY_WAITS[attempt]
