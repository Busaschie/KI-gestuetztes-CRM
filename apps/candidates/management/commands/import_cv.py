from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from agents.tasks import enqueue_agent
from apps.candidates.services import create_inbound_from_file, process_cv_inbound

SUFFIXES = {".pdf", ".docx", ".txt"}


class Command(BaseCommand):
    help = "Liest Lebensläufe (Dateien oder Ordner) ein. Standard: über die Warteschlange; --sync: sofort."

    def add_arguments(self, parser):
        parser.add_argument("paths", nargs="+")
        parser.add_argument("--sync", action="store_true", help="Direkt verarbeiten, ohne qcluster")

    def handle(self, *args, **opts):
        files = []
        for raw in opts["paths"]:
            p = Path(raw)
            if p.is_dir():
                files += sorted(f for f in p.rglob("*") if f.suffix.lower() in SUFFIXES)
            elif p.is_file():
                files.append(p)
            else:
                raise CommandError(f"Nicht gefunden: {p}")
        for f in files:
            item = create_inbound_from_file(f.name, f.read_bytes())
            if opts["sync"]:
                self.stdout.write(f"Lese {f.name} …")
                r = process_cv_inbound(item, on_progress=self._progress)
                style = self.style.SUCCESS if r.status == "assigned" else self.style.WARNING
                self.stdout.write(style(f"{f.name}: {r.status} – {r.message} {r.person or ''}"))
            else:
                enqueue_agent("cv_parser", inbound_id=item.pk)
                self.stdout.write(f"{f.name}: in Warteschlange (Eingang #{item.pk})")

    def _progress(self, chars: int, seconds: float):
        self.stdout.write(f"  … {chars} Zeichen nach {seconds:.0f} s")
        self.stdout.flush()
