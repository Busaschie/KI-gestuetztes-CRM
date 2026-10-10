from django.core.management.base import BaseCommand
from django_q.tasks import result

from agents.tasks import enqueue_agent


class Command(BaseCommand):
    help = "Schickt einen Auftrag an den Echo-Agenten und wartet auf das Ergebnis."

    def add_arguments(self, parser):
        parser.add_argument("text", nargs="?", default="Hallo Sandra")

    def handle(self, *args, **opts):
        task_id = enqueue_agent("echo", text=opts["text"])
        self.stdout.write(f"Auftrag {task_id} in die Warteschlange gelegt – warte auf Worker …")
        res = result(task_id, wait=30_000)  # Millisekunden
        if res is None:
            self.stderr.write(self.style.ERROR("Kein Ergebnis nach 30 s – läuft 'python manage.py qcluster'?"))
            return
        self.stdout.write(self.style.SUCCESS(f"Ergebnis: {res}"))
