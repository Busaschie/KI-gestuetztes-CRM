"""Ollama (lokal) – für die Entwicklung und als datensparsame Option. Kein OCR.

Die Antwort wird gestreamt: Solange das Modell Text liefert, gibt es kein Timeout. Abgebrochen wird nur,
wenn länger als `stall_timeout` nichts kommt oder die Gesamtdauer `max_seconds` überschreitet.
"""
import json
import time

import httpx

from agents.llm.base import LLMError, LLMProvider


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self, url: str, model: str, timeout: float = 1800, num_ctx: int = 16384,
                 num_predict: int = 4096, stall_timeout: float = 600, transport=None):
        self.model = model
        self.num_ctx = num_ctx
        self.num_predict = num_predict  # harte Obergrenze für die Antwortlänge in Tokens
        self.on_progress = None  # optional: Callback(zeichen, sekunden) für Fortschrittsanzeigen
        self.max_seconds = timeout
        # read = maximale Pause zwischen zwei Teilstücken (inkl. Einlesen des Prompts vor dem ersten Token)
        self.client = httpx.Client(
            base_url=url.rstrip("/"),
            timeout=httpx.Timeout(connect=10, read=stall_timeout, write=60, pool=10),
            transport=transport,
        )

    def complete_json(self, system: str, user: str, schema: dict) -> dict:
        payload = {
            "model": self.model,
            "stream": True,
            "think": False,  # Denk-Modelle (z. B. qwen3) überspringen das interne Nachdenken – viel schneller
            "format": schema,  # strukturierte Ausgabe nach JSON-Schema
            # Ollama nutzt sonst nur einen kleinen Kontext und schneidet lange CVs stillschweigend ab
            "options": {"temperature": 0, "num_ctx": self.num_ctx, "num_predict": self.num_predict},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        try:
            content = self._stream(payload)
        except _ThinkUnsupported:
            payload.pop("think")  # Modell ohne Denk-Modus
            content = self._stream(payload)
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            raise LLMError(f"Ollama lieferte kein gültiges JSON: {e}") from e

    def _stream(self, payload) -> str:
        started = time.monotonic()
        parts = []
        try:
            with self.client.stream("POST", "/api/chat", json=payload) as r:
                if r.status_code != 200:
                    body = r.read().decode("utf-8", errors="replace")
                    if r.status_code == 400 and "think" in body.lower() and "think" in payload:
                        raise _ThinkUnsupported
                    raise LLMError(f"Ollama {r.status_code}: {body[:300]}")
                size, last_report = 0, 0.0
                for line in r.iter_lines():
                    if not line.strip():
                        continue
                    chunk = json.loads(line)
                    if chunk.get("error"):
                        raise LLMError(f"Ollama: {chunk['error']}")
                    piece = chunk.get("message", {}).get("content", "")
                    parts.append(piece)
                    size += len(piece)
                    elapsed = time.monotonic() - started
                    if self.on_progress and elapsed - last_report >= 10:
                        self.on_progress(size, elapsed)
                        last_report = elapsed
                    if chunk.get("done"):
                        if chunk.get("done_reason") == "length":
                            raise LLMError(
                                f"Ollama: Antwort nach {self.num_predict} Tokens abgeschnitten (Modell {self.model}) – "
                                f"vermutlich Wiederholungsschleife. Ende: …{''.join(parts)[-200:]}"
                            )
                        break
                    if elapsed > self.max_seconds:
                        raise LLMError(
                            f"Ollama: Gesamtdauer über {self.max_seconds:.0f} s (Modell {self.model}) – abgebrochen. "
                            f"Ende der Ausgabe: …{''.join(parts)[-200:]}"
                        )
        except httpx.ConnectError as e:
            raise LLMError("Ollama nicht erreichbar – läuft 'ollama serve'?") from e
        except httpx.TimeoutException as e:
            raise LLMError(f"Ollama hängt – keine Ausgabe mehr (Modell {self.model})") from e
        except httpx.HTTPError as e:
            raise LLMError(f"Ollama-Verbindungsfehler: {e}") from e
        return "".join(parts)


class _ThinkUnsupported(Exception):
    pass
