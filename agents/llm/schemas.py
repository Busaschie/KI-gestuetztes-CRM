"""Strukturierte Ausgabe der CV-Auslese. Geschützte Merkmale gibt es hier bewusst nicht."""
import re
from typing import Literal

from pydantic import BaseModel, Field


class PositionOut(BaseModel):
    title: str
    company: str | None = None
    location: str | None = Field(None, description="Einsatzort, z. B. München")
    start: str | None = Field(None, description="JJJJ-MM oder JJJJ")
    end: str | None = Field(None, description="JJJJ-MM, JJJJ oder null wenn aktuell")
    is_current: bool = False
    tasks: list[str] = Field([], description="Aufgaben/Erfolge als kurze Stichpunkte, max. 6")


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
    headline: str | None = Field(None, description="Berufliches Kurzprofil, max. 10 Wörter – nicht der Name")
    summary: str | None = Field(None, description="3–5 Sätze, nur belegte Fakten")
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


# Obergrenzen für Listen: verhindern, dass kleine Modelle Einträge endlos wiederholen
MAX_ITEMS = {
    "positions": 25, "tasks": 6, "education": 12, "details": 6, "certifications": 15,
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


ONGOING = {"heute", "bis heute", "jetzt", "aktuell", "laufend", "today", "present", "now", "current", "prezent"}

ALIASES = {
    "vorname": "first_name", "firstname": "first_name", "given_name": "first_name",
    "nachname": "last_name", "lastname": "last_name", "surname": "last_name", "family_name": "last_name",
    "e-mail": "email", "mail": "email", "telefon": "phone", "linkedin": "linkedin_url",
    "wohnort": "city", "ort": "city", "land": "country",
    "qualifications": "skills", "kompetenzen": "skills", "ausbildung": "education", "zertifikate": "certifications",
}


def normalize_llm_output(raw) -> dict:
    """Fängt typische Abweichungen kleiner Modelle ab, bevor das Schema geprüft wird.

    - Antwort in einem Hüllobjekt ({"CVProfile": {...}}, {"profile": {...}})
    - eigene Feldnamen (vorname/nachname, name, full_name)
    """
    if not isinstance(raw, dict):
        return {}
    while len(raw) == 1 and isinstance(next(iter(raw.values())), dict):
        raw = next(iter(raw.values()))
    data = {ALIASES.get(k.lower(), k): v for k, v in raw.items()}
    for pos in data.get("positions") or []:
        if isinstance(pos, dict) and isinstance(pos.get("end"), str) and pos["end"].strip().lower() in ONGOING:
            pos["end"], pos["is_current"] = None, True
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
