from agents.llm.schemas import CVProfile
from apps.candidates.evaluation import evaluate

EXPECTED = {
    "person": {"first_name": "Max", "last_name": "Mustermann", "phone": "+49 12121212", "willing_to_relocate": True},
    "positions": [{"title": "Technischer Leiter", "company": "NewMoove", "start": "2012"},
                  {"title": "Softwareentwickler", "company": "Garmin", "start": "2007"}],
    "education": ["KI-Manager"],
    "skills": ["Python", "MongoDB"],
    "languages": [],
    "forbidden": ["01.01.1999"],
}


def test_full_match_and_rules():
    p = CVProfile.model_validate({
        "first_name": "Max", "last_name": "Mustermann", "phone": "+4912121212", "willing_to_relocate": True,
        "positions": [{"title": "Technischer Leiter", "company": "NewMoove Online Fitnessstudios", "start": "2012"},
                      {"title": "Softwareentwickler", "company": "Garmin", "start": "2007-01"}],
        "education": [{"title": "Weiterbildung zum KI-Manager", "institution": "cimdata", "kind": "weiterbildung"}],
        "skills": ["Python (FastAPI)", "Datenbanken (MongoDB)"],
    })
    r = evaluate(p, EXPECTED)
    assert r.score == 1.0 and r.passed_rules


def test_missing_items_invented_language_and_forbidden_are_reported():
    p = CVProfile.model_validate({
        "first_name": "Max", "last_name": "Mustermann", "summary": "Geboren am 01.01.1999",
        "positions": [{"title": "Technischer Leiter", "company": "NewMoove", "start": "2012"}],
        "languages": [{"name": "Englisch"}],
    })
    r = evaluate(p, EXPECTED)
    assert r.sections["Stationen"].missing == ["Softwareentwickler / Garmin (2007)"]
    assert r.sections["Aus-/Weiterbildung"].found == 0
    assert r.invented_languages == ["Englisch"] and r.forbidden_hits == ["01.01.1999"]
    assert not r.passed_rules and r.score < 0.5
