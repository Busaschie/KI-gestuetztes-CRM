import io

import docx
import pytest
from reportlab.pdfgen import canvas

from agents.llm.providers.fake import FakeProvider
from apps.candidates.models import CVDocument, DuplicateSuggestion
from apps.candidates.services import create_inbound_from_file, process_cv_inbound
from apps.communications.models import InboundItem
from apps.contacts.models import Employment, Person

CV_TEXT = (
    "Anna Hötter\nanna.hoetter@example.com\nKlagenfurt, Österreich\n"
    "Berufserfahrung\nseit 2019 Leiterin Vertrieb, Maschinenbau Kärnten GmbH, Führung von 8 Mitarbeitern\n"
    "2012–2019 Key Account Managerin, Muster AG\nSprachen: Deutsch (Muttersprache), Englisch (C1)\n"
)
LLM_ANSWER = {
    "first_name": "Anna", "last_name": "Hötter", "email": "anna.hoetter@example.com",
    "city": "Klagenfurt", "country": "AT", "headline": "Vertriebsleiterin Maschinenbau",
    "summary": "Vertriebsleiterin mit Führungserfahrung.",
    "positions": [
        {"title": "Leiterin Vertrieb", "company": "Maschinenbau Kärnten GmbH", "start": "2019", "end": None, "is_current": True},
        {"title": "Key Account Managerin", "company": "Muster AG", "start": "2012", "end": "2019", "is_current": False},
    ],
    "industries": ["Maschinenbau"], "skills": ["Vertrieb"],
    "languages": [{"name": "Deutsch", "level": "Muttersprache"}, {"name": "Englisch", "level": "C1"}],
    "years_experience": 13, "has_leadership": True,
}


def make_docx(text: str) -> bytes:
    d = docx.Document()
    for line in text.splitlines():
        d.add_paragraph(line)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def make_pdf(text: str | None) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    if text:
        y = 800
        for line in text.splitlines():
            c.drawString(40, y, line)
            y -= 16
    c.showPage()
    c.save()
    return buf.getvalue()


@pytest.fixture(autouse=True)
def fake_llm(settings, tmp_path):
    settings.LLM_PROVIDER = "fake"
    settings.MEDIA_ROOT = tmp_path
    FakeProvider.response = dict(LLM_ANSWER)
    FakeProvider.ocr_text = ""
    yield


def run(filename, data):
    return process_cv_inbound(create_inbound_from_file(filename, data))


@pytest.mark.django_db
def test_docx_creates_person_profile_cv_and_employment():
    r = run("hoetter.docx", make_docx(CV_TEXT))
    assert r.status == InboundItem.Status.ASSIGNED and r.created
    p = Person.objects.get()
    assert p.email == "anna.hoetter@example.com"
    assert p.candidate_profile.has_leadership is True
    assert p.candidate_profile.cvs.count() == 1
    emp = Employment.objects.get(person=p)
    assert emp.company.name == "Maschinenbau Kärnten GmbH" and emp.is_current


@pytest.mark.django_db
def test_pdf_with_text_is_read_without_ocr():
    r = run("hoetter.pdf", make_pdf(CV_TEXT))
    assert r.status == InboundItem.Status.ASSIGNED
    assert not CVDocument.objects.get().ocr_used


@pytest.mark.django_db
def test_identical_file_is_ignored():
    data = make_docx(CV_TEXT)
    run("a.docx", data)
    r = run("a-kopie.docx", data)
    assert r.status == InboundItem.Status.IGNORED
    assert CVDocument.objects.count() == 1


@pytest.mark.django_db
def test_new_version_same_email_keeps_old_version():
    run("v1.docx", make_docx(CV_TEXT))
    r = run("v2.docx", make_docx(CV_TEXT + "Neu: Zertifikat Projektmanagement\n"))
    assert r.status == InboundItem.Status.ASSIGNED and not r.created
    cvs = CVDocument.objects.order_by("created_at")
    assert cvs.count() == 2 and [c.is_current for c in cvs] == [False, True]
    assert Person.objects.count() == 1


@pytest.mark.django_db
def test_same_name_other_email_suggests_duplicate_but_does_not_merge():
    run("a.docx", make_docx(CV_TEXT))
    FakeProvider.response = {**LLM_ANSWER, "email": "anna.privat@example.com"}
    run("b.docx", make_docx(CV_TEXT + "privat\n"))
    assert Person.objects.count() == 2
    assert DuplicateSuggestion.objects.count() == 1


@pytest.mark.django_db
def test_scan_without_ocr_fails_visibly(settings):
    settings.LLM_PROVIDER = "ollama"
    settings.MISTRAL_API_KEY = ""
    r = run("scan.pdf", make_pdf(None))
    assert r.status == InboundItem.Status.FAILED and "Texterkennung" in r.message
    assert Person.objects.count() == 0


@pytest.mark.django_db
def test_scan_with_ocr_uses_ocr_text():
    FakeProvider.ocr_text = CV_TEXT
    r = run("scan.pdf", make_pdf(None))
    assert r.status == InboundItem.Status.ASSIGNED
    assert CVDocument.objects.get().ocr_used


@pytest.mark.django_db
def test_missing_name_is_taken_from_first_line():
    FakeProvider.response = {**LLM_ANSWER, "first_name": None, "last_name": None}
    r = run("x.docx", make_docx(CV_TEXT))
    assert r.status == InboundItem.Status.ASSIGNED and r.person.last_name == "Hötter"


@pytest.mark.django_db
def test_no_name_anywhere_goes_to_unassigned():
    FakeProvider.response = {**LLM_ANSWER, "first_name": None, "last_name": None}
    r = run("x.docx", make_docx("LEBENSLAUF\n" + CV_TEXT.split("\n", 1)[1]))
    assert r.status == InboundItem.Status.UNASSIGNED and "KI-Antwort" in r.message


@pytest.mark.django_db
def test_old_doc_format_is_rejected():
    r = run("alt.doc", b"x" * 500)
    assert r.status == InboundItem.Status.FAILED and ".docx" in r.message


@pytest.mark.django_db
def test_unexpected_error_marks_inbound_failed(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("kaputt")

    monkeypatch.setattr("apps.candidates.services._match_or_create_person", boom)
    item = create_inbound_from_file("x.docx", make_docx(CV_TEXT))
    r = process_cv_inbound(item)
    item.refresh_from_db()
    assert r.status == item.status == InboundItem.Status.FAILED and "kaputt" in item.error
