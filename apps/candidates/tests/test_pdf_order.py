"""PDF-Text in sichtbarer Reihenfolge (pdfminer) statt Speicherreihenfolge (pypdf)."""
import io

import pytest

from agents.tools.cv_grounding import split_blocks
from agents.tools.text_extract import extract_text

reportlab = pytest.importorskip("reportlab")


def _pdf(draw) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    draw(c)
    c.showPage()
    c.save()
    return buf.getvalue()


def test_scrambled_storage_order_is_read_top_down():
    rows = [(800, "Office Manager"), (785, "Alpha GmbH, Munich"), (770, "May 2024 – Present"),
            (755, "• Managed office operations and budgets."), (730, "Team Assistant"),
            (715, "Beta GmbH, Munich"), (700, "2020 – 2023"), (685, "• Coordinated calendars.")]

    def draw(c):
        for y, t in reversed(rows):  # unten zuerst gespeichert
            c.drawString(60, y, t)

    text = extract_text("cv.pdf", _pdf(draw)).text
    order = [text.index(t) for _, t in rows if t.isascii()]
    assert order == sorted(order)
    blocks = split_blocks(text)
    assert [b.title for b in blocks] == ["Office Manager", "Team Assistant"]


def test_two_columns_not_interleaved():
    def draw(c):
        for k in range(6):
            c.drawString(40, 800 - 15 * k, f"Left column line {k}")
            c.drawString(320, 800 - 15 * k, f"Right column line {k}")

    text = extract_text("cv.pdf", _pdf(draw)).text
    assert text.index("Left column line 5") < text.index("Right column line 0")


def test_sentence_line_is_never_title():
    text = """Office Manager
Alpha GmbH, Munich
2020 – 2023
• Managed budgets.
supported the team with onboarding and reporting tasks.
2018 – 2020
• Organised events."""
    blocks = split_blocks(text)
    assert blocks[1].title != "supported the team with onboarding and reporting tasks."


def test_sidebar_not_merged_with_left_aligned_date():
    """CV 2: linke Seitenleiste, Zeitraum linksbündig in eigener Zeile der Hauptspalte."""
    side = {770: "Munich, Germany", 740: "Office Management", 710: "Budget & Vendors"}
    main = [(800, "Office Manager | Executive Support"), (785, "Alpha GmbH, Munich"), (770, "May 2024 – Present"),
            (755, "\u2022 Support senior leadership."), (725, "Office Manager"), (710, "Beta GmbH, Munich"),
            (695, "May 2023 – September 2023"), (680, "\u2022 Managed budgets.")]

    def draw(c):
        for y, t in side.items():
            c.drawString(40, y, t)
        for y, t in main:
            c.drawString(250, y, t)

    text = extract_text("cv.pdf", _pdf(draw)).text
    assert "Munich, Germany May 2024" not in text and "Budget & Vendors May" not in text
    blocks = split_blocks(text)
    assert [b.title for b in blocks] == ["Office Manager | Executive Support", "Office Manager"]
    assert blocks[0].tasks == ["Support senior leadership."]


def test_right_aligned_date_joins_title_row():
    """Referenz-CV: 'Titel ........ 2012 – 2017' rechtsbündig in derselben Zeile."""
    def draw(c):
        c.drawString(60, 800, "Technischer Leiter")
        c.drawRightString(540, 800, "2012 – 2017")
        c.drawString(60, 785, "NewMoove GmbH | München")
        c.drawString(60, 770, "\u2022 Technische Leitung")
        c.drawString(60, 745, "Softwareentwickler")
        c.drawRightString(540, 745, "2007 – 2012")
        c.drawString(60, 730, "Garmin | Garching")

    text = extract_text("cv.pdf", _pdf(draw)).text
    assert "Technischer Leiter 2012 – 2017" in text
    assert [b.title for b in split_blocks(text)] == ["Technischer Leiter", "Softwareentwickler"]
