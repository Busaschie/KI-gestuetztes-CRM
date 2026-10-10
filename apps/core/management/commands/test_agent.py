from django.core.management.base import BaseCommand

from agents.tasks import run_agent


class Command(BaseCommand):
    help = "Schickt einen Auftrag an den Echo-Agenten und wartet auf das Ergebnis."

    def add_arguments(self, parser):
        parser.add_argument("text", nargs="?", default="Hallo Sandra")

    def handle(self, *args, **opts):
        result = run_agent.delay("echo", text=opts["text"])
        self.stdout.write(f"Auftrag {result.id} an Redis übergeben – warte auf Worker …")
        self.stdout.write(self.style.SUCCESS(f"Ergebnis: {result.get(timeout=30)}"))
