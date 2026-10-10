from django.core.management.base import BaseCommand
from django_q.models import Schedule

SCHEDULES = [
    # (Name, Funktion, Minuten)
    ("CV-Postfach abrufen", "apps.communications.tasks.fetch_cv_mailbox", 5),
]


class Command(BaseCommand):
    help = "Legt die zeitgesteuerten Aufgaben an bzw. aktualisiert sie (mehrfach ausführbar)."

    def handle(self, *args, **opts):
        for name, func, minutes in SCHEDULES:
            obj, created = Schedule.objects.update_or_create(
                name=name, defaults={"func": func, "schedule_type": Schedule.MINUTES, "minutes": minutes, "repeats": -1}
            )
            self.stdout.write(f"{'angelegt' if created else 'aktualisiert'}: {name} (alle {minutes} min)")
