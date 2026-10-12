from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from apps.candidates.models import CandidateProfile
from apps.candidates.services import reparse_profile


class Command(BaseCommand):
    help = "Liest Kandidatenprofile mit dem aktuellen Prompt neu aus (Profil-ID, E-Mail oder Name; --all für alle)."

    def add_arguments(self, parser):
        parser.add_argument("query", nargs="?", help="Profil-ID (aus der Admin-URL), E-Mail oder Namensteil")
        parser.add_argument("--all", action="store_true", help="Alle Profile neu auslesen")

    def handle(self, *args, **opts):
        qs = CandidateProfile.objects.select_related("person")
        if opts["all"]:
            profiles = list(qs)
        elif opts["query"]:
            q = opts["query"].strip()
            if q.isdigit():
                profiles = list(qs.filter(pk=int(q)))
            else:
                profiles = list(qs.filter(Q(person__email__iexact=q) | Q(person__last_name__icontains=q)
                                          | Q(person__first_name__icontains=q)))
            if len(profiles) > 1 and not q.isdigit():
                self.stdout.write("Mehrere Treffer – bitte mit Profil-ID aufrufen:")
                for p in profiles:
                    self.stdout.write(f"  {p.pk}: {p.person}")
                return
        else:
            raise CommandError("Profil-ID, E-Mail oder Name angeben – oder --all")
        if not profiles:
            raise CommandError("Kein passendes Profil gefunden")
        for p in profiles:
            self.stdout.write(f"Lese {p.person} (Profil {p.pk}) neu aus …")
            r = reparse_profile(p, on_progress=self._progress)
            style = self.style.SUCCESS if r.status == "assigned" else self.style.ERROR
            self.stdout.write(style(f"  {r.status}: {r.message}"))

    def _progress(self, chars: int, seconds: float):
        self.stdout.write(f"    … {chars} Zeichen nach {seconds:.0f} s")
        self.stdout.flush()
