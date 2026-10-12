"""Diagnose: zeigt für eine CV-Datei den ausgelesenen Text, die Dauer und die rohe KI-Antwort – ohne zu speichern."""
import json
import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from agents.llm.client import get_ocr
from agents.tools.text_extract import extract_text
from agents.llm.schemas import completeness_hint
from apps.candidates.services import parse_profile


class Command(BaseCommand):
    help = "CV-Auslese testen, ohne etwas in der Datenbank zu speichern."

    def add_arguments(self, parser):
        parser.add_argument("path")

    def handle(self, *args, **opts):
        f = Path(opts["path"])
        ex = extract_text(f.name, f.read_bytes(), ocr=get_ocr())
        self.stdout.write(self.style.MIGRATE_HEADING(f"Text: {len(ex.text)} Zeichen, OCR: {ex.ocr_used}, Scan ohne OCR: {ex.needs_ocr}"))
        self.stdout.write(ex.text[:400] + " …\n")
        model = settings.OLLAMA_MODEL if settings.LLM_PROVIDER == "ollama" else settings.MISTRAL_MODEL
        self.stdout.write(self.style.MIGRATE_HEADING(f"Frage {settings.LLM_PROVIDER} / {model} …"))
        t = time.perf_counter()
        raw, p = parse_profile(ex.text, on_progress=self._progress)
        self.stdout.write(f"Dauer: {time.perf_counter() - t:.0f} s\nRohe Antwort:")
        self.stdout.write(json.dumps(raw, ensure_ascii=False, indent=2)[:8000])
        self.stdout.write(self.style.SUCCESS(f"\nErkannt: {p.first_name} {p.last_name} | {p.email} | {p.phone} | {p.linkedin_url} | {len(p.positions)} Positionen"))
        if hint := completeness_hint(p, ex.text):
            self.stdout.write(self.style.WARNING(hint))

    def _progress(self, chars: int, seconds: float):
        self.stdout.write(f"  … {chars} Zeichen nach {seconds:.0f} s", ending="\n")
        self.stdout.flush()
