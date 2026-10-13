"""Transkription einzeln testen – ohne Bot und ohne Sprachmodell.

python manage.py transcribe <Eingangs-ID>        Sprachnachricht aus dem Admin (Eingänge)
python manage.py transcribe pfad\\zu\\datei.oga
"""
import time
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from agents.llm.base import LLMError
from django.conf import settings

from agents.llm.transcribe import get_transcriber, name_hints
from apps.communications.models import InboundItem


class Command(BaseCommand):
    help = "Wandelt eine Sprachnachricht in Text um und zeigt die Dauer"

    def add_arguments(self, parser):
        parser.add_argument("source", help="Eingangs-ID oder Dateipfad")

    def handle(self, source, **opts):
        if source.isdigit():
            item = InboundItem.objects.filter(pk=int(source)).first()
            if not item or not item.attachment:
                raise CommandError("Eingang nicht gefunden oder ohne Audiodatei.")
            with item.attachment.open("rb") as f:
                data, name = f.read(), Path(item.attachment.name).name
        else:
            path = Path(source)
            if not path.exists():
                raise CommandError(f"Datei nicht gefunden: {path}")
            data, name = path.read_bytes(), path.name

        hints = name_hints()
        model = settings.WHISPER_MODEL if settings.TRANSCRIBE_PROVIDER == "whisper" else settings.TRANSCRIBE_PROVIDER
        self.stdout.write(f"{name}: {len(data) / 1024:.0f} KB – Modell: {model}, Sprache: "
                          f"{settings.TRANSCRIBE_LANGUAGE or 'automatisch'}, Namenshinweise: {len(hints)}")
        t0 = time.monotonic()
        try:
            text = get_transcriber().transcribe(data, name, hints)
        except LLMError as e:
            raise CommandError(str(e)) from e
        self.stdout.write(self.style.SUCCESS(f"Fertig nach {time.monotonic() - t0:.1f} s:"))
        self.stdout.write(text or "(kein Text erkannt)")
