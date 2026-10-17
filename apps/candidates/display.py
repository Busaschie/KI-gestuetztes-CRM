"""Aufbereitung der JSON-Profildaten für die lesbare Ansicht im Admin."""
from django.template.loader import render_to_string

from agents.llm.schemas import _clean_nulls


def fmt_date(value) -> str:
    """'2019-03' → '03/2019', '2019' bleibt '2019'."""
    if not value:
        return ""
    value = str(value).strip()
    if len(value) == 7 and value[4] == "-":
        return f"{value[5:]}/{value[:4]}"
    return value


def period(item: dict, ongoing: bool = False) -> str:
    start, end = fmt_date(item.get("start")), fmt_date(item.get("end"))
    if ongoing or item.get("is_current"):
        end = "heute"
    if start and end:
        return f"{start} – {end}"
    return start or end


def _dicts(value) -> list[dict]:
    """Robust gegen alte oder von Hand bearbeitete Daten: Strings werden zu {'title': ...}."""
    out = []
    for entry in _clean_nulls(value) or []:  # alte Daten: "null" als Text
        if isinstance(entry, dict):
            out.append(entry)
        elif entry:
            out.append({"title": str(entry), "name": str(entry)})
    return out


def _strings(value) -> list[str]:
    return [str(v) for v in (_clean_nulls(value) or []) if v]


def profile_context(profile) -> dict:
    positions = [
        {**p, "period": period(p), "where": ", ".join(x for x in (p.get("company"), p.get("location")) if x)}
        for p in _dicts(profile.positions)
    ]
    education = [
        {**e, "period": period(e), "where": ", ".join(x for x in (e.get("institution"), e.get("location")) if x)}
        for e in _dicts(profile.education)
    ]
    other = [{**o, "period": period(o)} for o in _dicts(profile.other_experience)]
    return {
        "positions": positions,
        "education": education,
        "certifications": _dicts(profile.certifications),
        "other": other,
        "languages": _dicts(profile.languages),
        "tags": [
            ("Branchen", _strings(profile.industries)),
            ("Kompetenzen", _strings(profile.skills)),
            ("Persönliche Stärken", _strings(profile.strengths)),
            ("Interessen und Leistungen", _strings(profile.interests)),
        ],
    }


def render_profile(profile) -> str:
    return render_to_string("admin/candidates/profile_overview.html", profile_context(profile))
