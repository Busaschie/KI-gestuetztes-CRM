"""Vergleicht die CV-Auslese mit Referenz-CVs: zu jeder Datei gehört <name>.expected.json im selben Ordner."""
import json
import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from agents.llm.client import get_ocr
from agents.llm.schemas import CVProfile, fill_from_text, normalize_llm_output
from agents.tools.text_extract import extract_text
from apps.candidates.evaluation import evaluate
from apps.candidates.services import parse_profile


class Command(BaseCommand):
    help = "Bewertet die CV-Auslese gegen Referenz-CVs (*.expected.json). Speichert nichts in der Datenbank."

    def add_arguments(self, parser):
        parser.add_argument("folder", help="Ordner mit Referenz-CVs und *.expected.json")
        parser.add_argument(
            "--cached", action="store_true",
            help="Zuletzt gespeicherte KI-Antwort neu bewerten, ohne das Modell zu fragen (prüft Code-Änderungen in Sekunden)",
        )

    def handle(self, *args, **opts):
        folder = Path(opts["folder"])
        cases = [f for f in sorted(folder.iterdir())
                 if f.suffix.lower() in {".pdf", ".docx", ".txt"} and (folder / f"{f.stem}.expected.json").exists()]
        if not cases:
            raise CommandError(f"Keine Referenz-CVs mit .expected.json in {folder}")
        model = settings.OLLAMA_MODEL if settings.LLM_PROVIDER == "ollama" else settings.MISTRAL_MODEL
        self.stdout.write(self.style.MIGRATE_HEADING(f"Modell: {settings.LLM_PROVIDER} / {model}"))
        scores = []
        for f in cases:
            expected = json.loads((folder / f"{f.stem}.expected.json").read_text("utf-8"))
            t = time.perf_counter()
            text = extract_text(f.name, f.read_bytes(), ocr=get_ocr()).text
            out = folder / f"{f.stem}.result.{settings.LLM_PROVIDER}-{model.replace(':', '_')}.json"
            if opts["cached"]:
                if not out.exists():
                    raise CommandError(f"Keine gespeicherte Antwort: {out.name} – erst ohne --cached ausführen")
                raw = json.loads(out.read_text("utf-8"))["raw"]
                profile = fill_from_text(CVProfile.model_validate(normalize_llm_output(raw)), text)
            else:
                raw, profile = parse_profile(text, on_progress=self._progress)
            secs = time.perf_counter() - t
            res = evaluate(profile, expected)
            scores.append(res.score)
            self.stdout.write(self.style.MIGRATE_HEADING(f"\n{f.name}  –  {res.score:.0%}  ({secs:.0f} s)"))
            for name, sc in res.sections.items():
                line = f"  {name:<20} {sc.found:>2}/{sc.total:<2} {sc.ratio:>5.0%}"
                if sc.missing:
                    line += "   fehlt: " + "; ".join(map(str, sc.missing[:6])) + (" …" if len(sc.missing) > 6 else "")
                self.stdout.write(line)
            if res.forbidden_hits:
                self.stdout.write(self.style.ERROR(f"  VERBOTEN erfasst: {res.forbidden_hits}"))
            if res.invented_languages:
                self.stdout.write(self.style.ERROR(f"  ERFUNDENE Sprachen: {res.invented_languages}"))
            if res.passed_rules:
                self.stdout.write(self.style.SUCCESS("  Regeln eingehalten (nichts Verbotenes, nichts erfunden)"))
            if not opts["cached"]:
                out.write_text(json.dumps({"score": res.score, "seconds": round(secs), "raw": raw}, ensure_ascii=False, indent=2), "utf-8")
        self.stdout.write(self.style.SUCCESS(f"\nGesamt: {sum(scores) / len(scores):.0%} über {len(scores)} CV(s)"))

    def _progress(self, chars: int, seconds: float):
        self.stdout.write(f"  … {chars} Zeichen nach {seconds:.0f} s", ending="\n")
        self.stdout.flush()
