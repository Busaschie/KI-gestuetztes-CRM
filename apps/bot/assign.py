"""Kandidat per Sprache/Text einem bestehenden Auftrag zuordnen („Huber für Vertriebsleiter Muster AG vormerken“).

Vorschlag im Bot mit Bestätigung; legt „Kandidat im Auftrag“ (Stufe „Neu“) an. Mit „+ gesprochen“ wird zusätzlich
„Persönlich gesprochen“ gesetzt – dann gibt es keine automatische Standardabsage.
"""
from html import escape

from django.db import transaction
from django.utils import timezone

from apps.communications.models import InboundItem, Note
from apps.contacts.models import Person
from apps.core.models import Origin
from apps.jobs.models import Mandate
from apps.pipeline.models import Submission

from .extract import _similar, find_persons, person_label
from .models import BotDraft

OPEN = (Mandate.Status.ACTIVE, Mandate.Status.ON_HOLD, Mandate.Status.DRAFT)
MAX = 5


def find_candidates(name: str | None) -> list[Person]:
    return [p for p in find_persons(name) if hasattr(p, "candidate_profile")]


def find_mandates(position: str | None, company: str | None) -> list[Mandate]:
    pool = list(Mandate.objects.filter(status__in=OPEN).select_related("company"))
    if not position and not company:
        return pool if len(pool) <= MAX else []
    scored = []
    for m in pool:
        t = _similar(position, m.title) if position else None
        if position and position.casefold() in m.title.casefold():
            t = max(t, 0.9)
        c = max(_similar(company, m.company.name), _similar(company, m.company.name.split()[0])) if company else None
        if (t is not None and t < 0.6) or (c is not None and c < 0.6):
            continue
        scored.append(((t or 0) + (c or 0), m))
    scored.sort(key=lambda x: -x[0])
    if len(scored) > 1 and scored[0][0] - scored[1][0] >= 0.3:
        return [scored[0][1]]
    return [m for _, m in scored[:MAX]]


def prepare(draft: BotDraft) -> None:
    d = draft.data
    persons, mandates = find_candidates(d.get("person_name")), find_mandates(d.get("position"), d.get("company"))
    d["a"] = {
        "person_id": persons[0].pk if len(persons) == 1 else None,
        "person_candidates": [p.pk for p in persons] if len(persons) > 1 else [],
        "mandate_id": mandates[0].pk if len(mandates) == 1 else None,
        "mandate_candidates": [m.pk for m in mandates] if len(mandates) > 1 else [],
    }
    draft.data, draft.status = d, BotDraft.Status.AWAITING
    draft.person = persons[0] if len(persons) == 1 else None
    draft.save()


def _existing(a):
    if a.get("person_id") and a.get("mandate_id"):
        return Submission.objects.filter(candidate__person_id=a["person_id"], mandate_id=a["mandate_id"]).first()
    return None


def render(draft: BotDraft) -> tuple[str, list]:
    d, a, key = draft.data, draft.data["a"], f"d{draft.pk}"
    person = Person.objects.filter(pk=a.get("person_id")).first() if a.get("person_id") else None
    mandate = Mandate.objects.select_related("company").filter(pk=a.get("mandate_id")).first() if a.get("mandate_id") else None
    lines = ["🔗 <b>Kandidat zuordnen</b>"]
    if person:
        lines.append(f"👤 <b>Kandidat:</b> {escape(person_label(person))}")
    elif a.get("person_candidates"):
        lines.append(f"👤 <b>Kandidat:</b> „{escape(d.get('person_name') or '')}“ – mehrere Treffer, bitte wählen:")
    else:
        lines.append(f"👤 <b>Kandidat:</b> „{escape(d.get('person_name') or '?')}“ – kein Kandidat gefunden "
                     "(erst CV einlesen)")
    if mandate:
        lines.append(f"💼 <b>Auftrag:</b> {escape(str(mandate))}")
    elif a.get("mandate_candidates"):
        lines.append("💼 <b>Auftrag:</b> mehrere passende Aufträge, bitte wählen:")
    else:
        what = " ".join(x for x in (d.get("position"), d.get("company")) if x) or "?"
        lines.append(f"💼 <b>Auftrag:</b> „{escape(what)}“ – kein offener Auftrag gefunden")
    if d.get("note"):
        lines.append(f"📝 {escape(d['note'])}")

    buttons = []
    if a.get("person_candidates"):
        by_id = {p.pk: p for p in Person.objects.filter(pk__in=a["person_candidates"]).prefetch_related("employments__company")}
        buttons += [[(f"👤 {person_label(by_id[i])}"[:60], f"{key}:p{i}")] for i in a["person_candidates"] if i in by_id]
    if a.get("mandate_candidates"):
        buttons += [[(f"💼 {m}"[:60], f"{key}:j{m.pk}")]
                    for m in Mandate.objects.select_related("company").filter(pk__in=a["mandate_candidates"])]
    if person and mandate:
        if existing := _existing(a):
            lines.append(f"\nℹ️ Bereits zugeordnet (Stufe „{existing.get_stage_display()}“).")
        else:
            buttons.append([("✅ Zuordnen", f"{key}:ok"), ("✅ Zuordnen + gesprochen", f"{key}:ok2")])
    buttons.append([("🗑 Verwerfen + löschen", f"{key}:x")])
    return "\n".join(lines), buttons


def handle_action(draft: BotDraft, action: str, callback: dict, client) -> None:
    from .processing import _finish, _show, discard_draft

    a = draft.data["a"]
    if action.startswith("p") and action[1:].isdigit() and int(action[1:]) in a.get("person_candidates", []):
        a["person_id"], a["person_candidates"] = int(action[1:]), []
        draft.person_id = a["person_id"]
        _save_a(draft, a)
        client.answer_callback(callback["id"], "Kandidat gewählt")
        _show(draft, client)
    elif action.startswith("j") and action[1:].isdigit() and int(action[1:]) in a.get("mandate_candidates", []):
        a["mandate_id"], a["mandate_candidates"] = int(action[1:]), []
        _save_a(draft, a)
        client.answer_callback(callback["id"], "Auftrag gewählt")
        _show(draft, client)
    elif action in ("ok", "ok2") and a.get("person_id") and a.get("mandate_id") and not _existing(a):
        sub = save_assignment(draft, spoken=action == "ok2")
        client.answer_callback(callback["id"], "Zugeordnet")
        extra = " (persönlich gesprochen – keine Standardabsage)" if sub.spoken_with else ""
        _finish(draft, client, f"✅ Zugeordnet: {escape(str(sub.mandate))}{extra}")
    elif action == "x":
        discard_draft(draft, client, callback["message"].get("message_id"))
        client.answer_callback(callback["id"], "🗑 Verworfen – Nachricht gelöscht")
    else:
        client.answer_callback(callback["id"], "Nicht möglich")


def _save_a(draft, a):
    draft.data = {**draft.data, "a": a}
    draft.save(update_fields=["data", "person", "updated_at"])


@transaction.atomic
def save_assignment(draft: BotDraft, spoken: bool) -> Submission:
    a, item = draft.data["a"], draft.inbound
    person = Person.objects.select_related("candidate_profile").get(pk=a["person_id"])
    mandate = Mandate.objects.get(pk=a["mandate_id"])
    sub = Submission.objects.create(candidate=person.candidate_profile, mandate=mandate, spoken_with=spoken)
    origin = Origin.VOICE if item.channel == InboundItem.Channel.VOICE else Origin.MANUAL
    Note.objects.create(person=person, mandate=mandate, text=draft.data.get("note") or f"Für {mandate} vorgemerkt",
                        origin=origin)
    item.person, item.status, item.processed_at = person, InboundItem.Status.ASSIGNED, timezone.now()
    item.save(update_fields=["person", "status", "processed_at", "updated_at"])
    draft.person, draft.status = person, BotDraft.Status.SAVED
    draft.save(update_fields=["person", "status", "updated_at"])
    return sub
