from django.core.management.base import BaseCommand

from apps.communications.mailbox import fetch_mailbox


class Command(BaseCommand):
    help = "Ruft das CV-Postfach (IMAP) einmal ab. Die Auslese läuft danach über die Warteschlange (qcluster)."

    def add_arguments(self, parser):
        parser.add_argument("--sync", action="store_true", help="CVs sofort auslesen, ohne qcluster")

    def handle(self, *args, **opts):
        enqueue = None
        if opts["sync"]:
            from apps.candidates.services import process_cv_inbound

            def enqueue(item):
                self.stdout.write(f"  Lese {item.subject} … (lokales Modell: einige Minuten)")
                r = process_cv_inbound(item, origin="email", on_progress=self._progress)
                self.stdout.write(f"  {item.subject}: {r.status} – {r.message} {r.person or ''}")

        r = fetch_mailbox(enqueue=enqueue, log_line=self.stdout.write)
        self.stdout.write(self.style.SUCCESS(
            f"{r.messages} neue Mail(s): {r.attachments} CV-Anhang/Anhänge, {r.without_cv} ohne CV, "
            f"{r.skipped} bereits bekannt"
        ))

    def _progress(self, chars: int, seconds: float):
        self.stdout.write(f"    … {chars} Zeichen nach {seconds:.0f} s")
        self.stdout.flush()
