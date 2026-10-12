"""Strukturierte Ausgabe der CV-Auslese. Geschützte Merkmale gibt es hier bewusst nicht."""
import re
from typing import Literal

from pydantic import BaseModel, Field, PrivateAttr


class PositionOut(BaseModel):
    title: str
    company: str | None = None
    location: str | None = Field(None, description="Einsatzort, z. B. München")
    start: str | None = Field(None, description="JJJJ-MM oder JJJJ")
    end: str | None = Field(None, description="JJJJ-MM, JJJJ oder null wenn aktuell")
    is_current: bool = False
    tasks: list[str] = Field([], description="Aufgaben/Erfolge als kurze Stichpunkte, max. 8, in der Sprache des CV")


class EducationOut(BaseModel):
    title: str = Field(description="Abschluss oder Bezeichnung, z. B. Informationselektroniker, M.Sc. Informatik")
    institution: str | None = None
    location: str | None = None
    start: str | None = None
    end: str | None = None
    kind: Literal["ausbildung", "studium", "weiterbildung", "schule", "sonstiges"] = "sonstiges"
    details: list[str] = Field([], description="Schwerpunkte/Inhalte, kurz")


class CertificationOut(BaseModel):
    name: str
    issuer: str | None = None
    year: str | None = None


class OtherExperienceOut(BaseModel):
    title: str = Field(description="z. B. Wehrdienst Hauptgefreiter, Ehrenamt, Auslandsaufenthalt")
    organization: str | None = None
    start: str | None = None
    end: str | None = None


class LanguageOut(BaseModel):
    name: str
    level: str | None = Field(None, description="z. B. Muttersprache, C1, verhandlungssicher – nur wenn im CV genannt")


class CVProfile(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    linkedin_url: str | None = None
    city: str | None = None
    region: str | None = None
    country: str | None = Field(None, description="ISO-Code, z. B. AT, DE, RO")
    willing_to_relocate: bool | None = Field(None, description="true nur bei ausdrücklicher Umzugs-/Mobilitätsbereitschaft")
    headline: str | None = Field(None, description="Berufliches Kurzprofil, max. 10 Wörter, in der Sprache des CV – nicht der Name")
    summary: str | None = Field(None, description="Profiltext des CV wörtlich (ohne geschützte Merkmale); nur wenn keiner da ist, 2–3 eigene Sätze")
    positions: list[PositionOut] = []
    education: list[EducationOut] = []
    certifications: list[CertificationOut] = []
    other_experience: list[OtherExperienceOut] = []
    industries: list[str] = Field([], description="Branchen der Arbeitgeber, z. B. Medien, Automotive")
    skills: list[str] = Field([], description="Alle fachlichen Kompetenzen, Werkzeuge und Technologien")
    strengths: list[str] = Field([], description="Persönliche Stärken laut CV")
    interests: list[str] = Field([], description="Interessen und besondere Leistungen, z. B. Sport-Erfolge")
    languages: list[LanguageOut] = []
    years_experience: int | None = None
    has_leadership: bool | None = None
    _notes: list = PrivateAttr(default_factory=list)  # Hinweise aus dem Textabgleich – nicht Teil des Schemas


# Obergrenzen für Listen: verhindern, dass kleine Modelle Einträge endlos wiederholen
MAX_ITEMS = {
    "positions": 25, "tasks": 8, "education": 12, "details": 6, "certifications": 15,
    "other_experience": 8, "industries": 10, "skills": 40, "strengths": 12, "interests": 10, "languages": 10,
}


def strict_schema(model) -> dict:
    """Alle Felder als Pflichtfelder (Wert darf null sein) – sonst lassen kleine Modelle sie einfach weg.
    Dazu Obergrenzen (maxItems) für alle Listen."""
    schema = model.model_json_schema()

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                node["required"] = list(node["properties"])
                for name, prop in node["properties"].items():
                    if prop.get("type") == "array" and name in MAX_ITEMS:
                        prop["maxItems"] = MAX_ITEMS[name]
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(schema)
    return schema


CV_SCHEMA = strict_schema(CVProfile)


ONGOING = {"heute", "bis heute", "jetzt", "aktuell", "laufend", "today", "present", "now", "current", "prezent",
           "până în prezent", "pana in prezent", "ongoing", "to date"}

MONTHS = {
    # DE
    "januar": 1, "jänner": 1, "februar": 2, "märz": 3, "maerz": 3, "april": 4, "mai": 5, "juni": 6, "juli": 7,
    "august": 8, "september": 9, "oktober": 10, "november": 11, "dezember": 12,
    # EN
    "january": 1, "february": 2, "march": 3, "may": 5, "june": 6, "july": 7, "october": 10, "december": 12,
    # RO
    "ianuarie": 1, "februarie": 2, "martie": 3, "aprilie": 4, "iunie": 6, "iulie": 7, "septembrie": 9,
    "octombrie": 10, "noiembrie": 11, "decembrie": 12,
}
_MONTH_RE = re.compile(r"^([a-zäöüăâîșțşţ]+)\.?\s+((?:19|20)\d{2})$", re.I)
_NUMERIC_RE = re.compile(r"^(\d{1,2})[./-]((?:19|20)\d{2})$")


def normalize_date(value: str) -> str:
    """'May 2024' / 'Mai 2024' / 'mai 2024' / '05/2024' / '05.2024' → '2024-05'. Anderes bleibt unverändert."""
    v = value.strip()
    if m := _NUMERIC_RE.match(v):
        month = int(m.group(1))
        return f"{m.group(2)}-{month:02d}" if 1 <= month <= 12 else v
    if m := _MONTH_RE.match(v):
        name = m.group(1).lower()
        month = MONTHS.get(name) or next((n for k, n in MONTHS.items() if len(name) >= 3 and k.startswith(name)), None)
        if month:
            return f"{m.group(2)}-{month:02d}"
    return v

ALIASES = {
    "vorname": "first_name", "firstname": "first_name", "given_name": "first_name",
    "nachname": "last_name", "lastname": "last_name", "surname": "last_name", "family_name": "last_name",
    "e-mail": "email", "mail": "email", "telefon": "phone", "linkedin": "linkedin_url",
    "wohnort": "city", "ort": "city", "land": "country",
    "qualifications": "skills", "kompetenzen": "skills", "ausbildung": "education", "zertifikate": "certifications",
}


NULL_STRINGS = {"null", "none", "n/a", "na", "-", "unknown", "unbekannt", ""}


def _clean_nulls(value):
    """Kleine Modelle schreiben oft "null" als Text – wird zu None bzw. aus Listen entfernt."""
    if isinstance(value, str):
        return None if value.strip().lower() in NULL_STRINGS else value
    if isinstance(value, list):
        return [v for v in (_clean_nulls(x) for x in value) if v is not None]
    if isinstance(value, dict):
        return {k: _clean_nulls(v) for k, v in value.items()}
    return value


def normalize_llm_output(raw) -> dict:
    """Fängt typische Abweichungen kleiner Modelle ab, bevor das Schema geprüft wird.

    - Antwort in einem Hüllobjekt ({"CVProfile": {...}}, {"profile": {...}})
    - eigene Feldnamen (vorname/nachname, name, full_name)
    """
    if not isinstance(raw, dict):
        return {}
    while len(raw) == 1 and isinstance(next(iter(raw.values())), dict):
        raw = next(iter(raw.values()))
    data = {ALIASES.get(k.lower(), k): _clean_nulls(v) for k, v in raw.items()}
    for key in ("positions", "education", "other_experience"):
        for entry in data.get(key) or []:
            if not isinstance(entry, dict):
                continue
            for f in ("start", "end"):
                if isinstance(entry.get(f), str):
                    entry[f] = normalize_date(entry[f])
            if key == "positions" and isinstance(entry.get("end"), str) and entry["end"].strip().lower() in ONGOING:
                entry["end"], entry["is_current"] = None, True
    full = data.get("name") or data.get("full_name")
    if isinstance(full, str) and not data.get("last_name"):
        parts = full.strip().split()
        if len(parts) >= 2:
            data.setdefault("first_name", " ".join(parts[:-1]))
            data["last_name"] = parts[-1]
    return data


EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
LINKEDIN_RE = re.compile(r"(?:https?://)?(?:[a-z]{2,3}\.)?linkedin\.com/in/[^\s|,;)]+", re.I)
PHONE_RE = re.compile(r"(?:\+|00)\d[\d\s/().-]{7,}\d")
NAME_LINE_RE = re.compile(r"^[A-ZÄÖÜ][\w'’.-]+(?:[ -][A-ZÄÖÜ][\w'’.-]+){1,3}$")


def fill_from_text(profile: "CVProfile", text: str) -> "CVProfile":
    """Ergänzt Kontaktdaten, die sich sicher aus dem Text lesen lassen – nur wenn das Modell sie nicht geliefert hat."""
    if not profile.email and (m := EMAIL_RE.search(text)):
        profile.email = m.group(0).rstrip(".")
    if not profile.linkedin_url and (m := LINKEDIN_RE.search(text)):
        url = m.group(0)
        profile.linkedin_url = url if url.lower().startswith("http") else f"https://{url}"
    if not profile.phone and (m := PHONE_RE.search(text)):
        profile.phone = m.group(0).strip()
    if not profile.last_name and (name := _name_from_top_lines(text)):
        parts = name.split()
        profile.first_name, profile.last_name = " ".join(parts[:-1]), parts[-1]
    profile.languages = [lang for lang in profile.languages if _language_in_text(lang.name, text)]
    from agents.tools.cv_grounding import ground_positions

    edu_keys = [_norm_key(x) for e in profile.education for x in (e.institution, e.title) if x]
    profile.positions, notes = ground_positions(profile.positions, text, edu_keys)
    profile._notes.extend(notes)
    if profile.linkedin_url and not profile.linkedin_url.lower().startswith("http"):
        profile.linkedin_url = f"https://{profile.linkedin_url.strip()}"
    if profile.headline and profile.last_name and profile.last_name in profile.headline:
        profile.headline = None  # Modell hat den Namen als Kurzprofil eingetragen
    return profile


SKIP_LINE_RE = re.compile(r"^(seite|page|pagina)\s*\d+|^(lebenslauf|curriculum vitae|cv|resume|résumé|bewerbung)\b", re.I)


SECTION_WORDS = {
    "beruflicher", "werdegang", "berufserfahrung", "berufliche", "erfahrung", "profil", "kurzprofil", "kontakt",
    "ausbildung", "bildung", "persönliche", "daten", "kenntnisse", "fähigkeiten", "sprachen", "qualifikationen",
    "zusammenfassung", "lebenslauf", "tabellarischer", "experience", "education", "profile", "summary", "skills",
    "contact", "personal", "details", "work", "senior", "junior", "manager", "entwickler", "entwicklerin",
}


def _name_from_top_lines(text: str, max_lines: int = 5) -> str | None:
    """Sucht in den ersten Zeilen eine Zeile, die wie ein Name aussieht; Kopfzeilen werden übersprungen."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines[:max_lines]:
        if SKIP_LINE_RE.match(line):
            continue
        words = {w.lower().strip(".:") for w in line.split()}
        looks_like_name = NAME_LINE_RE.match(line) and not words & SECTION_WORDS
        return line if looks_like_name else None  # erste echte Zeile entscheidet – kein Raten weiter unten
    return None


# Sprachnamen in den Sprachen der Kandidaten (DE, EN, RO). Schlüssel = normalisierter Name.
LANGUAGE_VARIANTS = {
    "deutsch": ["deutsch", "german", "germană", "germana", "muttersprache deutsch"],
    "englisch": ["englisch", "english", "engleză", "engleza"],
    "französisch": ["französisch", "franzoesisch", "french", "franceză", "franceza"],
    "italienisch": ["italienisch", "italian", "italiană", "italiana"],
    "spanisch": ["spanisch", "spanish", "spaniolă", "spaniola"],
    "rumänisch": ["rumänisch", "rumaenisch", "romanian", "română", "romana"],
    "ungarisch": ["ungarisch", "hungarian", "maghiară", "maghiara"],
    "russisch": ["russisch", "russian", "rusă", "rusa"],
    "polnisch": ["polnisch", "polish", "poloneză"],
    "tschechisch": ["tschechisch", "czech", "cehă"],
    "kroatisch": ["kroatisch", "croatian", "croată"],
    "slowenisch": ["slowenisch", "slovenian", "slovenă"],
    "türkisch": ["türkisch", "turkish", "turcă"],
}


def _language_in_text(name: str, text: str) -> bool:
    """Schutz vor erfundenen Sprachen: Die Sprache muss als eigenes Wort im CV stehen."""
    key = (name or "").strip().lower()
    variants = next((v for k, v in LANGUAGE_VARIANTS.items() if key == k or key in v), [key])
    lowered = text.lower()
    return any(re.search(rf"(?<!\w){re.escape(v)}(?!\w)", lowered) for v in variants if v)


_RANGE_RE = re.compile(
    r"(?:(?:19|20)\d{2})\s*(?:–|—|-|bis|to|până la)\s*(?:[A-Za-zäöüÄÖÜăâîșț.]+\s+)?"
    r"(?:(?:19|20)\d{2}|present|heute|today|now|jetzt|aktuell|prezent|current)"
    r"|(?:seit|since|din)\s+(?:[A-Za-zäöüăâîșț.]+\s+)?(?:19|20)\d{2}",
    re.I,
)


def count_date_ranges(text: str) -> int:
    """Zählt Zeiträume im CV-Text (z. B. 'May 2023 – September 2023', '2015–2021', 'seit 2026')."""
    return len(_RANGE_RE.findall(text))


def completeness_hint(profile: "CVProfile", text: str) -> str:
    """Hinweis, wenn deutlich weniger Einträge erkannt wurden, als der Text Zeiträume enthält (Grundsatz 8)."""
    parts = list(profile._notes)
    ranges = count_date_ranges(text)
    found = len(profile.positions) + len(profile.education) + len(profile.other_experience)
    if ranges - found >= 2:
        parts.append(f"{ranges} Zeiträume im Text, aber nur {found} Stationen/Ausbildungen erkannt "
                     f"({len(profile.positions)} Berufsstationen) – bitte prüfen")
    return ("Hinweis: " + "; ".join(parts)) if parts else ""


def _norm_key(s: str) -> str:
    return re.sub(r"[^\w]+", " ", s.lower()).strip()
