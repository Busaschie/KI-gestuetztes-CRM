"""Textabgleich: stellt den Fehlerfall aus CV Nr. 2 nach (erfundene Firmen)."""
from agents.llm.schemas import CVProfile, fill_from_text, normalize_llm_output
from agents.tools.cv_grounding import split_blocks

TEXT = """OFFICE MANAGER | EXECUTIVE SUPPORT
Office Manager and Executive Support professional with 5+ years of experience.
WORK EXPERIENCE
Office Manager | Executive Support
Alpha Boards GmbH, Munich
May 2024 – Present
• Support senior leadership with executive coordination, internal
communications, presentations and key meetings.
• Manage office operations, vendor relationships, budgets.
Office Manager
Beta Group GmbH, Munich
May 2023 – September 2023
(concurrent with Master's degree)
• Supported leadership with administrative and operational coordination.
• Managed budgets, invoices, and vendor relationships.
Office Manager | Team Assistant
Gamma GmbH, Munich
September 2022 – February 2023
• Managed HR onboarding, compliance, and personnel records.
• Coordinated executive calendars and cross-team meetings.
Guest Relations Specialist | Luxury Hospitality
Mykonos, Greece | 2015–2021
• Delivered personalized service to international clients.
EDUCATION
International Master in Digital Marketing
Rome Business School
2023 – 2024
Bachelor of Arts in English Language
National University of Athens
2008 – 2013
SKILLS
Internal Communications, Employee Experience, Budget & Vendors
"""

# So ähnlich hat llama3.1 geantwortet: Aufgaben verschoben, Daten "null", Station erfunden, eine fehlt
BAD = {
    "first_name": "Erika", "last_name": "Muster",
    "positions": [
        {"title": "Office Manager | Executive Support", "company": "Alpha Boards GmbH", "location": "Munich",
         "start": "2024-05", "end": None, "is_current": True,
         "tasks": ["Supported leadership with administrative and operational coordination.",
                   "Managed budgets, invoices, and vendor relationships."]},
        {"title": "Office Manager | Team Assistant", "company": "Gamma GmbH", "location": "Munich, Germany",
         "start": "2022-09", "end": "2023-02", "tasks": []},
        {"title": "Office Manager | Executive Support", "company": "Beta Group GmbH", "location": "Munich",
         "start": "null", "end": "null", "tasks": ["Managed travel and calendars", "Internal Communications"]},
        {"title": "Tour Guide | Adventure Travel", "company": None, "location": "Mykonos, Greece",
         "start": "2015", "end": "2021", "tasks": []},
    ],
    "education": [
        {"title": "International Master in Digital Marketing", "institution": "Rome Business School",
         "location": "null", "start": "2023", "end": "2024", "kind": "weiterbildung"},
        {"title": "Bachelor of Arts in English Language", "institution": "National University of Athens",
         "start": "2008", "end": "2013", "kind": "studium"},
    ],
}


def ground(raw):
    return fill_from_text(CVProfile.model_validate(normalize_llm_output(raw)), TEXT)


def test_blocks_are_found_with_headers_and_wrapped_bullets():
    blocks = split_blocks(TEXT)
    assert [b.title for b in blocks[:4]] == [
        "Office Manager | Executive Support", "Office Manager", "Office Manager | Team Assistant",
        "Guest Relations Specialist | Luxury Hospitality"]
    assert blocks[0].tasks[0].endswith("presentations and key meetings.")
    assert blocks[1].tasks[0] == "(concurrent with Master's degree)"
    assert blocks[3].rest == "Mykonos, Greece" and blocks[3].start == "2015"


def test_bad_llm_output_is_checked_not_rebuilt():
    p = ground(BAD)
    # erfundene Station entfernt, Rest bleibt in der Reihenfolge des Modells (kein Umbau nach Layout)
    assert [x.company for x in p.positions] == ["Alpha Boards GmbH", "Gamma GmbH", "Beta Group GmbH"]
    alpha, gamma, beta = p.positions
    assert alpha.tasks == BAD["positions"][0]["tasks"]  # im Text belegt → bleibt
    assert "Managed travel and calendars" not in beta.tasks  # Prompt-Beispiel, nicht im CV → entfernt
    assert (beta.start, beta.end) == (None, None)  # "null" als Text bereinigt
    assert p.education[0].location is None
    assert any("Tour Guide" in n and "entfernt" in n for n in p._notes)
    assert any("Aufgabe(n) nicht im Text belegt" in n for n in p._notes)


def test_invented_company_and_year_are_reported():
    raw = {**BAD, "positions": [{"title": "Office Manager", "company": "Omega AG", "start": "2019-01", "end": "2023-09",
                                 "tasks": []}]}
    p = ground(raw)
    assert p.positions[0].company is None
    assert any("Omega AG" in n for n in p._notes) and any("2019" in n for n in p._notes)


def test_unassigned_range_is_reported_but_education_is_not():
    raw = {**BAD, "positions": [BAD["positions"][0]]}
    p = ground(raw)
    unassigned = [n for n in p._notes if n.startswith("Zeitraum keiner Station")]
    assert len(unassigned) == 3  # Beta, Gamma, Mykonos – nicht die beiden Ausbildungen
    assert not any("2008" in n for n in unassigned)


def test_correct_output_stays_untouched_and_no_notes():
    good = {"last_name": "Muster", "positions": [
        {"title": "Office Manager | Executive Support", "company": "Alpha Boards GmbH", "location": "Munich",
         "start": "2024-05", "is_current": True,
         "tasks": ["Support senior leadership with executive coordination, internal communications, presentations and key meetings.",
                   "Manage office operations, vendor relationships, budgets."]},
        {"title": "Office Manager", "company": "Beta Group GmbH", "location": "Munich", "start": "2023-05", "end": "2023-09",
         "tasks": ["(concurrent with Master's degree)", "Supported leadership with administrative and operational coordination.",
                   "Managed budgets, invoices, and vendor relationships."]},
        {"title": "Office Manager | Team Assistant", "company": "Gamma GmbH", "location": "Munich", "start": "2022-09", "end": "2023-02",
         "tasks": ["Managed HR onboarding, compliance, and personnel records.", "Coordinated executive calendars and cross-team meetings."]},
        {"title": "Guest Relations Specialist | Luxury Hospitality", "location": "Mykonos, Greece", "start": "2015", "end": "2021",
         "tasks": ["Delivered personalized service to international clients."]},
    ], "education": BAD["education"]}
    p = ground(good)
    assert p._notes == [] and [x.title for x in p.positions][1] == "Office Manager"


def test_text_without_dates_leaves_output_alone():
    p = fill_from_text(CVProfile.model_validate({"last_name": "X", "positions": [{"title": "Koch", "company": "Hotel"}]}),
                       "Erfahrung als Koch im Hotel")
    assert p.positions[0].title == "Koch" and p._notes == []


def test_page_break_and_title_in_date_line_layout():
    text = ("BERUFSERFAHRUNG\nTechnischer Leiter 2012 – 2017\nNewMoove GmbH | München — Start-up\n• Aufbau der Systeme\n"
            "IT-Techniker 1996 – 1997\nSeite 3 von 4\nESCOM Computertechnik, München\n• Wartung von PCs\n")
    blocks = split_blocks(text)
    assert [(b.header, b.tasks) for b in blocks] == [
        (["Technischer Leiter", "NewMoove GmbH | München — Start-up"], ["Aufbau der Systeme"]),
        (["IT-Techniker", "ESCOM Computertechnik, München"], ["Wartung von PCs"]),
    ]


def test_month_word_must_be_a_real_month():
    from agents.tools.cv_grounding import parse_range

    assert parse_range("Technischer Leiter 2012 – 2017")[:2] == ("2012", "2017")
    assert parse_range("Office Manager May 2023 – Sept. 2023")[:2] == ("2023-05", "2023-09")
    assert parse_range("Weiterbildung seit 2026")[:3] == ("2026", None, True)


def test_spaced_heading_and_bullet_with_date():
    text = """R E S E A R C H   &   I N D U S T R Y   E X P E R I E N C E
Doctoral Researcher Jun 2023 – present
Example University  ·  Essen, Germany
•  Developed a model.
Research Assistant
Apr 2021 – Apr 2023 (2 years)
•  Built pipelines.
V O L U N T E E R I N G
•  Example Network (Ambassador, 2022 – present)"""
    blocks = split_blocks(text)
    assert [b.title for b in blocks] == ["Doctoral Researcher", "Research Assistant"]
    assert blocks[1].tasks == ["Built pipelines."]
