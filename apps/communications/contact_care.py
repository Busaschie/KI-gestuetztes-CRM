"""Kontaktpflege – Basis (P1 Punkt 6): Wiedervorlagen nach festen Regeln und höchstens N Vorschläge pro Tag.

Regeln (täglich vor dem Briefing):
- Vermittelte Kandidaten: nach CONTACT_CARE_MONTHS_PLACED Monaten ohne Kontakt.
- Ansprechpartner früherer Kunden: nach CONTACT_CARE_MONTHS_CLIENTS Monaten ohne Kontakt.
  Kunden mit laufendem Auftrag bekommen keine Vorschläge (Sandra spricht ohnehin mit ihnen).
- Vorgemerkte Kandidaten: am Datum „Vorgemerkt bis“.
„Letzter Kontakt“ wird automatisch gesetzt (Notiz, gesendete Nachricht, „Kontakt erledigt“).
"""
from datetime import timedelta

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from apps.contacts.models import Person, client_contact_q

from .models import FollowUp, mark_contacted

CARE_REASONS = (FollowUp.Reason.RULE_6_MONTHS, FollowUp.Reason.ON_HOLD, FollowUp.Reason.JOB_CHANGE)


def _open_mandate_statuses():
    from apps.jobs.models import Mandate
    return (Mandate.Status.ACTIVE, Mandate.Status.ON_HOLD, Mandate.Status.DRAFT)


def _since(person) -> str:
    if person.last_contacted_at:
        return f"letzter Kontakt {timezone.localtime(person.last_contacted_at):%d.%m.%Y}"
    return "noch kein Kontakt erfasst"


def _no_contact_since(qs, months: int, now):
    limit = now - timedelta(days=30 * months)
    return qs.filter(Q(last_contacted_at__lt=limit) | Q(last_contacted_at__isnull=True, created_at__lt=limit))


def plan_contact_care(today=None) -> int:
    """Legt fällige Kontaktpflege-Wiedervorlagen an (je Person höchstens eine offene). Gibt die Anzahl zurück."""
    from apps.candidates.models import CandidateProfile
    from apps.pipeline.models import Submission

    now = timezone.now()
    today = today or timezone.localdate()
    busy = FollowUp.objects.filter(done_at__isnull=True, reason__in=CARE_REASONS).values("person_id")
    base = Person.objects.filter(no_contact_care=False).exclude(pk__in=busy)
    created, seen = 0, set()

    placed = _no_contact_since(
        base.filter(candidate_profile__submissions__stage=Submission.Stage.PLACED), settings.CONTACT_CARE_MONTHS_PLACED, now
    ).distinct()
    for person in placed:
        sub = (Submission.objects.filter(candidate__person=person, stage=Submission.Stage.PLACED)
               .select_related("mandate__company").order_by("-updated_at").first())
        FollowUp.objects.create(person=person, mandate=sub.mandate if sub else None, due_date=today,
                                reason=FollowUp.Reason.RULE_6_MONTHS,
                                text=f"Kontaktpflege: vermittelt ({sub.mandate if sub else '?'}) – {_since(person)}"[:255])
        seen.add(person.pk)
        created += 1

    open_ = _open_mandate_statuses()
    running = Q(mandates__status__in=open_) | Q(employments__is_current=True, employments__company__mandates__status__in=open_)
    running_ids = Person.objects.filter(running).values("pk")
    clients = _no_contact_since(
        base.filter(pk__in=Person.objects.filter(client_contact_q()).values("pk")).exclude(pk__in=running_ids),
        settings.CONTACT_CARE_MONTHS_CLIENTS, now,
    ).exclude(pk__in=seen).prefetch_related("employments__company")
    for person in clients:
        emp = next((e for e in person.employments.all() if e.is_current), None)
        where = f"früherer Kunde {emp.company.name}" if emp else "früherer Kunde"
        FollowUp.objects.create(person=person, due_date=today, reason=FollowUp.Reason.RULE_6_MONTHS,
                                text=f"Kontaktpflege: {where} – {_since(person)}"[:255])
        seen.add(person.pk)
        created += 1

    on_hold = CandidateProfile.objects.filter(on_hold_until__isnull=False, person__in=base).exclude(person_id__in=seen)
    for profile in on_hold.select_related("person"):
        if FollowUp.objects.filter(person=profile.person, reason=FollowUp.Reason.ON_HOLD,
                                   due_date=profile.on_hold_until).exists():
            continue  # für dieses Datum schon angelegt (auch wenn erledigt)
        FollowUp.objects.create(person=profile.person, due_date=profile.on_hold_until, reason=FollowUp.Reason.ON_HOLD,
                                text=f"Vorgemerkter Kandidat – wieder ansprechen ({profile.headline or 'Profil'})"[:255])
        created += 1
    return created


def suggestions(today=None):
    """Fällige Kontaktvorschläge, älteste zuerst (das Briefing zeigt höchstens CONTACT_SUGGESTIONS_PER_DAY)."""
    today = today or timezone.localdate()
    return (FollowUp.objects.filter(done_at__isnull=True, reason__in=CARE_REASONS, due_date__lte=today)
            .select_related("person", "mandate").order_by("due_date", "pk"))


def mark_done(follow_up: FollowUp) -> None:
    follow_up.done_at = timezone.now()
    follow_up.save(update_fields=["done_at", "updated_at"])
    if follow_up.person_id:
        mark_contacted(follow_up.person_id, follow_up.done_at)


def postpone(follow_up: FollowUp, days: int = 30) -> None:
    follow_up.due_date = timezone.localdate() + timedelta(days=days)
    follow_up.save(update_fields=["due_date", "updated_at"])


def opt_out(follow_up: FollowUp) -> None:
    follow_up.done_at = timezone.now()
    follow_up.save(update_fields=["done_at", "updated_at"])
    if follow_up.person_id:
        Person.objects.filter(pk=follow_up.person_id).update(no_contact_care=True)
