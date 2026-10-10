"""CV-Import: Datei → Text → KI-Profil → Person/Kandidatenprofil/CV-Version (P1 Punkt 1 und 2).

Grundsätze: Originale bleiben unverändert, nichts wird automatisch zusammengeführt (Dubletten nur
als Vorschlag), jeder Eingang zeigt sein Ergebnis (InboundItem.status), nichts wird erfunden.
"""
import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from pydantic import ValidationError

from agents.llm.base import LLMError
from agents.llm.client import get_llm, get_ocr
from agents.llm.schemas import CV_SCHEMA, CVProfile, fill_from_text, normalize_llm_output
from agents.tools.text_extract import UnsupportedFile, extract_text
from apps.communications.models import InboundItem
from apps.contacts.models import Company, Employment, Person, PersonOrigin
from apps.core.models import Origin

from .models import CandidateProfile, CVDocument, DuplicateSuggestion

log = logging.getLogger(__name__)
PROMPT = (Path(__file__).resolve().parents[2] / "agents" / "llm" / "prompts" / "cv_extract.md").read_text("utf-8")
MAX_CHARS = 40_000


@dataclass
class ImportResult:
    status: str
    person: Person | None = None
    created: bool = False
    message: str = ""


def create_inbound_from_file(filename: str, data: bytes, channel=InboundItem.Channel.FILE_IMPORT) -> InboundItem:
    """Legt den Eingang mit Original-Datei an – vor jeder Verarbeitung, damit nichts verloren geht."""
    item = InboundItem(channel=channel, subject=filename)
    item.attachment.save(filename, ContentFile(data), save=False)
    item.save()
    return item


def process_cv_inbound(item: InboundItem, origin: str = Origin.IMPORT, on_progress=None) -> ImportResult:
    """Verarbeitet einen Eingang. Jeder Ausgang – auch ein unerwarteter Fehler – wird am Eingang sichtbar."""
    try:
        return _process(item, origin, on_progress)
    except Exception as e:  # noqa: BLE001 – nichts darf still im Status "Eingegangen" hängen bleiben
        log.exception("CV-Import fehlgeschlagen (Eingang %s)", item.pk)
        item.status, item.error, item.processed_at = InboundItem.Status.FAILED, f"Unerwarteter Fehler: {e}", timezone.now()
        item.save(update_fields=["status", "error", "processed_at", "updated_at"])
        return ImportResult(InboundItem.Status.FAILED, message=item.error)


def _process(item: InboundItem, origin: str, on_progress=None) -> ImportResult:
    item.attachment.open("rb")
    data = item.attachment.read()
    item.attachment.close()
    filename = item.subject or Path(item.attachment.name).name

    def finish(status, message="", person=None, created=False):
        item.status, item.error, item.person, item.processed_at = status, message, person, timezone.now()
        item.save()
        return ImportResult(status, person, created, message)

    checksum = hashlib.sha256(data).hexdigest()
    existing = CVDocument.objects.filter(checksum=checksum).select_related("profile__person").first()
    if existing:
        return finish(InboundItem.Status.IGNORED, "Identische Datei bereits vorhanden", existing.profile.person)

    try:
        extracted = extract_text(filename, data, ocr=get_ocr())
    except UnsupportedFile as e:
        return finish(InboundItem.Status.FAILED, str(e))
    except LLMError as e:
        return finish(InboundItem.Status.FAILED, f"Texterkennung fehlgeschlagen: {e}")
    if extracted.needs_ocr:
        return finish(InboundItem.Status.FAILED, "Gescanntes PDF – Texterkennung nicht verfügbar (MISTRAL_API_KEY fehlt)")
    if len(extracted.text) < 100:
        return finish(InboundItem.Status.FAILED, "Kaum Text gefunden – ist das ein Lebenslauf?")
    item.raw_text = extracted.text[:5000]

    try:
        raw, profile_data = parse_profile(extracted.text, on_progress=on_progress)
    except (LLMError, ValidationError) as e:
        return finish(InboundItem.Status.FAILED, f"KI-Auslese fehlgeschlagen: {e}")

    if not profile_data.last_name:
        return finish(
            InboundItem.Status.UNASSIGNED,
            f"Kein Name im Lebenslauf erkannt. KI-Antwort: {json.dumps(raw, ensure_ascii=False)[:400]}",
        )

    with transaction.atomic():
        person, created = _match_or_create_person(profile_data)
        PersonOrigin.objects.get_or_create(person=person, origin=origin, detail="")
        _update_profile(person, profile_data)
        _update_employments(person, profile_data, origin)
        CVDocument(
            profile=person.candidate_profile,
            original_filename=filename,
            received_at=item.created_at,
            origin=origin,
            extracted_text=extracted.text,
            ocr_used=extracted.ocr_used,
            is_current=True,
        ).file.save(filename, ContentFile(data), save=True)
        _suggest_duplicates(person)
    return finish(InboundItem.Status.ASSIGNED, "Neues Profil" if created else "Neue CV-Version", person, created)


def parse_profile(text: str, on_progress=None) -> tuple[dict, CVProfile]:
    """Text → KI → bereinigtes Profil. Gemeinsam genutzt von Import, cv_debug und cv_eval."""
    llm = get_llm()
    if on_progress and hasattr(llm, "on_progress"):
        llm.on_progress = on_progress
    raw = llm.complete_json(PROMPT, text[:MAX_CHARS], CV_SCHEMA)
    return raw, fill_from_text(CVProfile.model_validate(normalize_llm_output(raw)), text)


def _match_or_create_person(p: CVProfile) -> tuple[Person, bool]:
    """Eindeutige Treffer nur über E-Mail oder LinkedIn-Profil; Namensgleichheit → Dubletten-Vorschlag."""
    q = Q()
    if p.email:
        q |= Q(email__iexact=p.email.strip())
    if p.linkedin_url:
        q |= Q(linkedin_url__iexact=p.linkedin_url.strip())
    person = Person.objects.filter(q).first() if q else None
    created = person is None
    if created:
        person = Person()
    # Nur leere Felder füllen – von Hand gepflegte Daten werden nicht überschrieben
    for field in ("first_name", "last_name", "email", "phone", "linkedin_url", "city", "region", "country"):
        value = getattr(p, field)
        if value and not getattr(person, field):
            setattr(person, field, value.strip()[: Person._meta.get_field(field).max_length])
    person.save()
    return person, created


def _update_profile(person: Person, p: CVProfile) -> None:
    profile, _ = CandidateProfile.objects.get_or_create(person=person)
    # Der neueste CV ist die beste Quelle für die ausgelesenen Felder
    profile.headline = (p.headline or profile.headline)[:255]
    profile.summary = p.summary or profile.summary
    profile.positions = [pos.model_dump() for pos in p.positions]
    profile.education = [e.model_dump() for e in p.education]
    profile.certifications = [c.model_dump() for c in p.certifications]
    profile.other_experience = [o.model_dump() for o in p.other_experience]
    profile.industries = p.industries
    profile.skills = p.skills
    profile.strengths = p.strengths
    profile.interests = p.interests
    profile.languages = [lang.model_dump() for lang in p.languages]
    if p.willing_to_relocate is not None:
        profile.willing_to_relocate = p.willing_to_relocate
    if p.years_experience is not None:
        profile.years_experience = p.years_experience
    if p.has_leadership is not None:
        profile.has_leadership = p.has_leadership
    profile.save()


def _update_employments(person: Person, p: CVProfile, origin: str) -> None:
    for pos in p.positions:
        if not (pos.is_current and pos.company):
            continue
        company = Company.objects.filter(name__iexact=pos.company.strip()).first() or Company.objects.create(
            name=pos.company.strip()[:255]
        )
        Employment.objects.get_or_create(
            person=person, company=company, title=pos.title[:255],
            defaults={"is_current": True, "origin": origin},
        )


def _suggest_duplicates(person: Person) -> None:
    if not person.last_name:
        return
    same_name = Person.objects.filter(
        first_name__iexact=person.first_name, last_name__iexact=person.last_name
    ).exclude(pk=person.pk)
    for other in same_name:
        a, b = sorted([person, other], key=lambda x: x.pk)
        if not DuplicateSuggestion.objects.filter(person_a=a, person_b=b).exists():
            DuplicateSuggestion.objects.create(person_a=a, person_b=b, reason="Gleicher Vor- und Nachname")
