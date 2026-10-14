from datetime import datetime, time, timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone
from django_q.models import Schedule

SCHEDULES = [
    # (Name, Funktion, Minuten)
    ("CV-Postfach abrufen", "apps.communications.tasks.fetch_cv_mailbox", 5),
    ("Verträge: geplanten Versand ausführen", "apps.clients.services.send_due_contracts", 1),
]


DAILY = [
    # (Name, Funktion, Uhrzeit HH:MM aus den Einstellungen)
    ("Telegram-Briefing", "apps.bot.briefing.send_daily_briefing", lambda: settings.TELEGRAM_BRIEFING_TIME),
    ("Verträge: Erinnerungen an Kunden", "apps.clients.services.send_contract_reminders",
     lambda: settings.CONTRACT_REMINDER_TIME),
]


def next_run_at(hhmm: str) -> datetime:
    hour, minute = (int(x) for x in hhmm.split(":"))
    now = timezone.localtime()
    run = timezone.make_aware(datetime.combine(now.date(), time(hour, minute)))
    return run if run > now else run + timedelta(days=1)


class Command(BaseCommand):
    help = "Legt die zeitgesteuerten Aufgaben an bzw. aktualisiert sie (mehrfach ausführbar)."

    def handle(self, *args, **opts):
        for name, func, minutes in SCHEDULES:
            obj, created = Schedule.objects.update_or_create(
                name=name, defaults={"func": func, "schedule_type": Schedule.MINUTES, "minutes": minutes, "repeats": -1}
            )
            self.stdout.write(f"{'angelegt' if created else 'aktualisiert'}: {name} (alle {minutes} min)")
        for name, func, hhmm in DAILY:
            obj, created = Schedule.objects.update_or_create(
                name=name, defaults={
                    "func": func, "schedule_type": Schedule.DAILY, "repeats": -1, "next_run": next_run_at(hhmm()),
                },
            )
            self.stdout.write(f"{'angelegt' if created else 'aktualisiert'}: {name} (täglich {hhmm()})")
