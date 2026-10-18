"""Notiz, Person und Wiedervorlage aus einer Nachricht ziehen (Sprachmodell) und Personen zuordnen."""
import unicodedata
from datetime import date, timedelta
from difflib import SequenceMatcher
from pathlib import Path

from django.db.models import Q
from django.utils import timezone
from pydantic import BaseModel, Field, ValidationError

from agents.llm.base import LLMError
from agents.llm.client import get_llm
from apps.contacts.models import Person

PROMPT = (Path(__file__).resolve().parents[2] / "agents" / "llm" / "prompts" / "voice_note.md").read_text(encoding="utf-8")
WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
MAX_CANDIDATES = 5


class NoteOut(BaseModel):
    intent: str = Field("note", description='"note", "mandate" (neuer Suchauftrag) oder "assign" (Kandidat zu Auftrag)')
    person_name: str | None = None
    company: str | None = None
    note: str = ""
    follow_up_date: str | None = Field(None, description="JJJJ-MM-TT oder null")
    follow_up_text: str | None = None
    position: str | None = None
    location: str | None = None
    fee_percent: float | None = None


SCHEMA = NoteOut.model_json_schema()
SCHEMA["required"] = list(SCHEMA["properties"])


def _calendar(today: date, days: int = 21) -> str:
    lines = [f"Heute: {WEEKDAYS[today.weekday()]}, {today:%Y-%m-%d}"]
    for i in range(1, days + 1):
        d = today + timedelta(days=i)
        lines.append(f"{WEEKDAYS[d.weekday()]} {d:%Y-%m-%d}")
    return "\n".join(lines)


def extract_note(text: str, today: date | None = None) -> dict:
    """Gibt ein bereinigtes dict zurück: person_name, company, note, follow_up_date (ISO|None), follow_up_text."""
    today = today or timezone.localdate()
    user = f"Kalender:\n{_calendar(today)}\n\nNachricht:\n{text}"
    raw = get_llm().complete_json(PROMPT, user, SCHEMA)
    try:
        clean = {k: (None if k not in ("note", "intent") and isinstance(v, str)
                     and v.strip().lower() in ("", "null", "none") else v)
                 for k, v in (raw or {}).items()
                 if k in NoteOut.model_fields and not (k in ("note", "intent") and v is None)}
        if isinstance(clean.get("fee_percent"), str):  # z. B. "20 %" oder "20,5"
            try:
                clean["fee_percent"] = float(clean["fee_percent"].replace("%", "").replace(",", ".").strip())
            except ValueError:
                clean["fee_percent"] = None
        out = NoteOut.model_validate(clean)
    except ValidationError as e:
        raise LLMError(f"Antwort des Sprachmodells unbrauchbar: {e.errors()[0]['msg']}") from e
    data = out.model_dump()
    intent = str(data.get("intent") or "").strip().lower()
    data["intent"] = intent if intent in ("mandate", "assign") else "note"
    if data["fee_percent"] is not None and not 0 < data["fee_percent"] <= 50:
        data["fee_percent"] = None  # unplausibel (Hörfehler)
    for key in ("person_name", "company", "follow_up_text", "position", "location"):
        if isinstance(data[key], str) and data[key].strip().lower() in ("", "null", "none"):
            data[key] = None
    data["note"] = (data["note"] or text).strip()
    data["follow_up_date"] = _valid_date(data["follow_up_date"], today)
    if data["follow_up_date"] and not data["follow_up_text"]:
        data["follow_up_text"] = data["note"][:255]
    if not data["follow_up_date"]:
        data["follow_up_text"] = None
    return data


def _valid_date(value, today: date) -> str | None:
    """Nur Daten von heute bis in 2 Jahren – alles andere ist vermutlich ein Lesefehler."""
    try:
        d = date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None
    return d.isoformat() if today <= d <= today + timedelta(days=730) else None


# --- Personen zuordnen ----------------------------------------------------------------------------

def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").casefold())
    return "".join(c for c in s if not unicodedata.combining(c)).replace("ß", "ss")


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def find_persons(name: str | None, company: str | None = None) -> list[Person]:
    """Bis zu 5 passende Personen, beste zuerst. Toleriert kleine Schreib-/Hörfehler (z. B. Maier/Meier)."""
    tokens = [t for t in (name or "").replace(",", " ").split() if len(t) >= 2]
    if not tokens:
        return []
    query = Q()
    for t in tokens:
        query |= Q(last_name__icontains=t[:4]) | Q(first_name__icontains=t[:4])
    pool = list(Person.objects.filter(query).prefetch_related("employments__company")[:300])
    if not pool:  # Hörfehler am Wortanfang: über alle Nachnamen ähnlich suchen
        pool = list(Person.objects.prefetch_related("employments__company")[:5000])

    scored = []
    for p in pool:
        last = max((_similar(t, p.last_name) for t in tokens), default=0)
        first = max((_similar(t, p.first_name) for t in tokens), default=0) if p.first_name else 0
        if last < 0.75 and not (len(tokens) == 1 and first >= 0.9):
            continue
        score = last * 2 + (first if first >= 0.75 else 0)
        if company and any(_similar(company, e.company.name) >= 0.75 for e in p.employments.all()):
            score += 1
        scored.append((score, p))
    scored.sort(key=lambda x: -x[0])
    if scored and len(scored) > 1 and scored[0][0] - scored[1][0] >= 1:
        return [scored[0][1]]  # klarer Favorit (z. B. Vor- und Nachname oder Firma passen)
    return [p for _, p in scored[:MAX_CANDIDATES]]


def person_label(p: Person) -> str:
    emp = next((e for e in p.employments.all() if e.is_current), None)
    return f"{p} – {emp.company.name}" if emp else str(p)
