"""Bewertung der CV-Auslese gegen ein Soll-Ergebnis (Referenz-CVs mit *.expected.json).

Gemessen wird je Bereich, wie viele der erwarteten Angaben gefunden wurden, und ob Verbotenes
auftaucht (z. B. Geburtsdatum) oder etwas erfunden wurde (z. B. nicht genannte Sprachen).
"""
import json
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from agents.llm.schemas import CVProfile


def _norm(s) -> str:
    return re.sub(r"[^\w]+", " ", str(s or "").lower()).strip()


def _similar(a, b, threshold=0.75) -> bool:
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return False
    return a in b or b in a or SequenceMatcher(None, a, b).ratio() >= threshold


def _digits(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


@dataclass
class SectionScore:
    found: int = 0
    total: int = 0
    missing: list = field(default_factory=list)

    @property
    def ratio(self) -> float:
        return self.found / self.total if self.total else 1.0


@dataclass
class EvalResult:
    sections: dict
    forbidden_hits: list
    invented_languages: list

    @property
    def score(self) -> float:
        total = sum(s.total for s in self.sections.values())
        found = sum(s.found for s in self.sections.values())
        return found / total if total else 1.0

    @property
    def passed_rules(self) -> bool:
        return not self.forbidden_hits and not self.invented_languages


def _keywords(expected: list, items: list) -> SectionScore:
    """Jeder erwartete Begriff muss in irgendeinem ausgelesenen Eintrag vorkommen."""
    blob = [_norm(json.dumps(i, ensure_ascii=False)) if not isinstance(i, str) else _norm(i) for i in items]
    sc = SectionScore(total=len(expected))
    for kw in expected:
        if any(_norm(kw) in b for b in blob):
            sc.found += 1
        else:
            sc.missing.append(kw)
    return sc


def evaluate(profile: CVProfile, expected: dict) -> EvalResult:
    sections = {}

    person = expected.get("person", {})
    sc = SectionScore(total=len(person))
    for key, want in person.items():
        got = getattr(profile, key, None)
        ok = _digits(got).endswith(_digits(want)[-8:]) if key == "phone" else (
            got == want if isinstance(want, bool) else _similar(got, want, 0.9))
        sc.found += ok
        if not ok:
            sc.missing.append(f"{key}: erwartet {want!r}, erhalten {got!r}")
    sections["Person"] = sc

    sc = SectionScore(total=len(expected.get("positions", [])))
    for want in expected.get("positions", []):
        hit = any(
            (p.start or "")[:4] == want["start"][:4]
            and (_similar(p.company, want.get("company")) or _similar(p.title, want.get("title")))
            for p in profile.positions
        )
        sc.found += hit
        if not hit:
            sc.missing.append(f"{want.get('title')} / {want.get('company')} ({want['start']})")
    sections["Stationen"] = sc

    sc = SectionScore(total=len(expected.get("education", [])))
    for want in expected.get("education", []):
        hit = any(_similar(e.title, want) or _similar(e.institution, want) for e in profile.education)
        sc.found += hit
        if not hit:
            sc.missing.append(want)
    sections["Aus-/Weiterbildung"] = sc

    for label, key in [("Zertifikate", "certifications"), ("Sonstiges", "other_experience"),
                       ("Kompetenzen", "skills"), ("Branchen", "industries"),
                       ("Stärken", "strengths"), ("Interessen", "interests")]:
        if key in expected:
            sections[label] = _keywords(expected[key], [x if isinstance(x, str) else x.model_dump() for x in getattr(profile, key)])

    dump = profile.model_dump_json()
    forbidden_hits = [f for f in expected.get("forbidden", []) if f.lower() in dump.lower()]
    allowed = [_norm(lang) for lang in expected.get("languages", [])]
    invented = [lang.name for lang in profile.languages if _norm(lang.name) not in allowed]
    return EvalResult(sections, forbidden_hits, invented)
