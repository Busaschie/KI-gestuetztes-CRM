"""Vertrags-PDF im Layout von Sandras Vorlage („Recruitment & Executive Search Partnership“).

Je Vertrag werden Kunde, Adresse, Position, Anstellungsart, Honorar und Fristen eingesetzt.
Mit for_signature=True steht über der Unterschriftszeile des Kunden der (unsichtbare) Platzhalter
{{signature, r1}}, den Documenso beim Hochladen in ein Unterschriftsfeld für Empfänger 1 umwandelt.
"""
import io
from html import escape
from pathlib import Path

from django.conf import settings
from django.utils import timezone
from reportlab.lib.colors import HexColor, white
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Frame, Paragraph, Spacer, Table, TableStyle

ASSETS = Path(settings.BASE_DIR) / "static" / "contract"

CRIMSON = HexColor("#A3203F")
GOLD = HexColor("#B07A3B")
TEXT = HexColor("#2B2B2B")
GREY = HexColor("#6B6B6B")
HEADER_BG = HexColor("#FBF1EF")
CARD_BG = HexColor("#F8F4F1")
BORDER = HexColor("#EADFDC")
PINK_BOX = HexColor("#FBEDEF")

COUNTRIES = {
    "AT": "Österreich", "DE": "Deutschland", "CH": "Schweiz", "RO": "Rumänien", "IT": "Italien",
    "HU": "Ungarn", "SI": "Slowenien", "HR": "Kroatien", "CZ": "Tschechien", "SK": "Slowakei", "PL": "Polen",
}

class ContractLayoutError(ValueError):
    pass


_fonts_done = False
F = {"regular": "Helvetica", "medium": "Helvetica", "semibold": "Helvetica-Bold", "bold": "Helvetica-Bold",
     "script": "Helvetica-Oblique"}


def _register_fonts():
    """Poppins (Überschriften/Text) und Dancing Script (Slogan), beide OFL – Rückfall: Helvetica."""
    global _fonts_done
    if _fonts_done:
        return
    files = {"regular": "Poppins-Regular", "medium": "Poppins-Medium", "semibold": "Poppins-SemiBold",
             "bold": "Poppins-Bold", "script": "DancingScript"}
    for key, name in files.items():
        path = ASSETS / "fonts" / f"{name}.ttf"
        if path.exists():
            try:
                pdfmetrics.registerFont(TTFont(name, str(path)))
                F[key] = name
            except Exception:  # noqa: BLE001 – kaputte Schrift: Standardschrift verwenden
                pass
    _fonts_done = True


def _fmt_percent(value) -> str:
    return f"{float(value):g}".replace(".", ",") + " %"


def contract_context(contract) -> dict:
    """Alle Werte, die im Vertrag stehen – auch für Tests und die Vorschau."""
    company, mandate, fee = contract.company, contract.mandate, contract.fee_model
    signatory = contract.get_signer() or company.signatory
    city_line = " ".join(x for x in (company.postal_code, company.city) if x)
    return {
        "date": timezone.localdate().strftime("%d.%m.%Y"),
        "client_name": company.name,
        "client_address": [x for x in (company.street, city_line, COUNTRIES.get(company.country, company.country)) if x],
        "client_signer": str(signatory) if signatory else "",
        "position": mandate.title,
        "employment_type": mandate.employment_type or "Festanstellung",
        "percent": _fmt_percent(contract.percent),
        "guarantee_months": fee.guarantee_months,
        "protection_years": fee.protection_years,
        "interview_days": fee.first_interviews_days,
        "payment_days": fee.payment_days,
        "deviations": contract.deviations.strip(),
        "law": settings.CONTRACT_GOVERNING_LAW,
        "contractor_name": settings.CONTRACTOR_NAME,
        "contractor_address": [x.strip() for x in settings.CONTRACTOR_ADDRESS.split("|") if x.strip()],
        "contractor_tax_id": settings.CONTRACTOR_TAX_ID,
        "contractor_signer": settings.CONTRACTOR_SIGNER or "Auftragnehmerin",
    }


def build_contract_pdf(contract, for_signature: bool = False) -> bytes:
    _register_fonts()
    c = contract_context(contract)
    buf = io.BytesIO()
    cv = Canvas(buf, pagesize=A4)
    cv.setTitle(f"Recruitment Partnership – {c['client_name']}")
    cv.setAuthor(c["contractor_name"] or c["contractor_signer"])
    W, H = A4
    M = 34  # Rand

    _header(cv, c, W, H, M)
    _cards(cv, c, W, H, M)
    _kpis(cv, c, W, H, M)
    body_top = H - 336
    annex = _body(cv, c, W, M, body_top, bottom=62)
    _signatures(cv, c, W, M, for_signature)
    cv.showPage()
    if annex:
        _annex(cv, c, W, H, M)
        cv.showPage()
    cv.save()
    return buf.getvalue()


# --- Teile ----------------------------------------------------------------------------------------

def _header(cv, c, W, H, M):
    cv.setFillColor(HEADER_BG)
    cv.rect(0, H - 172, W, 172, stroke=0, fill=1)
    logo = ASSETS / "logo.png"
    if logo.exists():
        cv.drawImage(str(logo), M, H - 72, 48, 48, mask="auto")
    cv.setFillColor(CRIMSON)
    cv.setFont(F["bold"], 15)
    cv.drawString(M + 60, H - 45, "KOHLWEG")
    cv.setFillColor(GREY)
    cv.setFont(F["regular"], 6.5)
    cv.drawString(M + 60, H - 59, _spaced("HEADHUNTING & DIRECT SEARCH"))
    cv.setFont(F["script"], 12.5)
    cv.drawRightString(W - M, H - 42, "Die richtigen Menschen.")
    cv.setFillColor(CRIMSON)
    cv.drawRightString(W - M, H - 58, "Nachhaltige Wirkung.")

    cv.setFillColor(GOLD)
    cv.setFont(F["semibold"], 6.5)
    cv.drawString(M, H - 96, _spaced("VERTRAG ÜBER RECRUITING- UND EXECUTIVE-SEARCH-DIENSTLEISTUNGEN"))
    cv.setFillColor(TEXT)
    cv.setFont(F["regular"], 21)
    cv.drawString(M, H - 120, "Recruitment & Executive Search")
    cv.setFillColor(CRIMSON)
    cv.setFont(F["bold"], 22)
    cv.drawString(M, H - 146, "Partnership.")
    # Datum als Pille
    cv.setStrokeColor(CRIMSON)
    cv.setLineWidth(0.8)
    cv.roundRect(W - M - 70, H - 152, 70, 20, 10, stroke=1, fill=0)
    cv.setFillColor(TEXT)
    cv.setFont(F["medium"], 8)
    cv.drawCentredString(W - M - 35, H - 145, c["date"])


def _cards(cv, c, W, H, M):
    gap, top, h = 12, H - 184, 80
    w = (W - 2 * M - gap) / 2
    for i, (label, color, name, lines) in enumerate([
        ("AUFTRAGGEBER", CRIMSON, c["client_name"], c["client_address"]),
        ("AUFTRAGNEHMERIN", GOLD, c["contractor_name"], c["contractor_address"] + ([c["contractor_tax_id"]] if c["contractor_tax_id"] else [])),
    ]):
        x = M + i * (w + gap)
        cv.setFillColor(CARD_BG)
        cv.roundRect(x, top - h, w, h, 8, stroke=0, fill=1)
        cv.setFillColor(color)
        lw = pdfmetrics.stringWidth(_spaced(label), F["semibold"], 6) + 16
        cv.roundRect(x + 12, top - 22, lw, 12, 6, stroke=0, fill=1)
        cv.setFillColor(white)
        cv.setFont(F["semibold"], 6)
        cv.drawString(x + 20, top - 18.5, _spaced(label))
        cv.setFillColor(TEXT)
        _fit_string(cv, name, x + 12, top - 38, w - 24, F["semibold"], 9.5)
        cv.setFillColor(GREY)
        cv.setFont(F["regular"], 8)
        for j, line in enumerate(lines[:4]):
            _fit_string(cv, line, x + 12, top - 51 - j * 11, w - 24, F["regular"], 8)


def _kpis(cv, c, W, H, M):
    gap, top, h = 10, H - 274, 50
    w = (W - 2 * M - 3 * gap) / 4
    items = [
        (c["percent"], "Honorar vom Jahresbrutto inkl. Zielbonus"),
        (f"{c['interview_days']} Tage", "bis zu den ersten Interviews"),
        (f"{c['guarantee_months']} Monate", "Nachbesetzungsgarantie"),
        ("100 %", "Diskretion im gesamten Prozess"),
    ]
    label_style = ParagraphStyle("kpi", fontName=F["regular"], fontSize=6.8, leading=8.5, textColor=GREY)
    for i, (value, label) in enumerate(items):
        x = M + i * (w + gap)
        cv.setStrokeColor(BORDER)
        cv.setLineWidth(0.8)
        cv.roundRect(x, top - h, w, h, 8, stroke=1, fill=0)
        cv.setFillColor(CRIMSON)
        cv.setFont(F["semibold"], 16)
        cv.drawString(x + 10, top - 22, value)
        p = Paragraph(escape(label), label_style)
        _, ph = p.wrap(w - 20, 30)
        p.drawOn(cv, x + 10, top - 28 - ph)


def _styles():
    return {
        "h": ParagraphStyle("h", fontName=F["semibold"], fontSize=9.2, leading=11.5, textColor=TEXT,
                            spaceBefore=7, spaceAfter=2),
        "p": ParagraphStyle("p", fontName=F["regular"], fontSize=7.6, leading=10.2, textColor=TEXT, alignment=TA_LEFT),
        "li": ParagraphStyle("li", fontName=F["regular"], fontSize=7.6, leading=10.2, textColor=TEXT,
                             leftIndent=9, bulletIndent=1, spaceAfter=1),
    }


def _hl(text) -> str:
    """Hervorgehobener Wert (rot, fett) wie in der Vorlage."""
    return f'<font name="{F["semibold"]}" color="#A3203F">{escape(str(text))}</font>'


def _b(text) -> str:
    return f'<font name="{F["semibold"]}">{escape(str(text))}</font>'


def _heading(num, title, st):
    return Paragraph(f'<font color="#A3203F" size="12">{num}</font>&nbsp;&nbsp;{escape(title)}', st["h"])


def _bullets(items, st):
    return [Paragraph(t, st["li"], bulletText="•") for t in items]


def _body(cv, c, W, M, top, bottom) -> bool:
    """Zeichnet die beiden Textspalten. Gibt True zurück, wenn die Sondervereinbarungen auf Seite 2 (Anlage) müssen."""
    st = _styles()
    gap = 22
    col_w = (W - 2 * M - gap) / 2
    annex = bool(c["deviations"])  # Seite 1 ist voll – Sondervereinbarungen immer als Anlage auf Seite 2
    left, right = _stories(c, st, col_w, annex)
    for x, story in ((M, left), (M + col_w + gap, right)):
        frame = Frame(x, bottom, col_w, top - bottom, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        frame.addFromList(story, cv)  # entfernt alles, was passt, aus story
        if story:  # lieber klarer Fehler als abgeschnittener Vertrag
            raise ContractLayoutError("Vertragstext passt nicht auf eine Seite")
    return annex


def _annex(cv, c, W, H, M):
    """Seite 2: Anlage mit den Sondervereinbarungen."""
    st = _styles()
    story = [
        _heading("09", "Anlage – Abweichende Vereinbarungen", st),
        Paragraph(f"Zwischen {_b(c['client_name'])} und {_b(c['contractor_name'] or c['contractor_signer'])} – "
                  f"Position {_b(c['position'])}, Vertrag vom {c['date']}.", st["p"]),
        Spacer(1, 6),
        Paragraph(escape(c["deviations"]).replace("\n", "<br/>"), st["p"]),
    ]
    frame = Frame(M, 62, W - 2 * M, H - 62 - M, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    frame.addFromList(story, cv)
    if story:
        raise ContractLayoutError("Sondervereinbarungen zu lang (mehr als eine Seite Anlage)")


def _stories(c, st, col_w, annex: bool):
    """annex=True: letzter Punkt unter 08 verweist auf die Anlage (Seite 2) statt des Schlusssatzes."""
    who = escape(c["contractor_signer"])
    left = [
        _heading("01", "Zusammenarbeit und Zielsetzung", st),
        Paragraph(f"{who} unterstützt die {_b(c['client_name'])} dabei, einen qualifizierten "
                  f"{_b(c['position'])} zu identifizieren, anzusprechen und für eine "
                  f"{_b(c['employment_type'])} zu gewinnen.", st["p"]),
        _heading("02", "Leistungen im Rahmen der Zusammenarbeit", st),
        Paragraph("Für eine effiziente und erfolgreiche Personalsuche werden folgende Leistungen erbracht:", st["p"]),
        *_bullets([
            "Erstellung eines detaillierten Stellenprofils in enger Abstimmung",
            "Direkte Ansprache und Vorauswahl geeigneter Kandidaten",
            "Persönliche Interviews zur ersten Einschätzung",
            "Koordination der Vorstellungsgespräche",
            "Begleitung während des gesamten Auswahlprozesses",
            "Rückmeldung an nicht berücksichtigte Kandidaten",
        ], st),
        Spacer(1, 5),
        _box(f'<font name="{F["semibold"]}" color="#A3203F">Schnelligkeit:</font> Erste Interviews können in der '
             f"Regel innerhalb von {c['interview_days']} Tagen stattfinden. Bei früheren Treffern wird der Prozess "
             "beschleunigt.", st, col_w),
        _heading("03", "Honorar", st),
        *_bullets([
            f"Das Honorar beträgt {_hl(c['percent'])} des vertraglich vereinbarten Gesamtjahresbruttos inklusive "
            "Zielbonus des ersten Jahres der vermittelten Person.",
            "Es wird bei erfolgreicher Vermittlung fällig und nach der Unterzeichnung des Anstellungsvertrages "
            "durch den Kandidaten.",
            f"Die Zahlung ist innerhalb von {c['payment_days']} Tagen nach Rechnungsstellung zu leisten.",
            "Alle Beträge verstehen sich netto. Die Rechnungsstellung erfolgt im Reverse-Charge-Verfahren; "
            "die Umsatzsteuer schuldet der Auftraggeber.",
        ], st),
    ]
    right = [
        _heading("04", "Direkteinstellungen", st),
        Paragraph(f"Wird eine von {who} vorgeschlagene Person – unabhängig von der Position – direkt eingestellt, "
                  "bleibt das vereinbarte Honorar gültig.", st["p"]),
        Spacer(1, 3),
        Paragraph(f"Werden Kandidaten, die von {who} vorgestellt wurden, innerhalb von "
                  f"{_hl(_years(c['protection_years']))} nach ihrer Vorstellung eingestellt – auch auf eine andere "
                  f"Position –, wird ebenfalls das Honorar von {_hl(c['percent'])} fällig. Ein Kandidat gilt als "
                  f"vorgestellt, sobald {who} sein Profil an den Auftraggeber übermittelt hat.", st["p"]),
        _heading("05", "Nachbesetzungsgarantie", st),
        Paragraph(f"Sollte die vermittelte Person innerhalb von {_hl(_months(c['guarantee_months']))} nach Eintritt "
                  "aus eigenem Entschluss oder durch Kündigung des Unternehmens ausscheiden, verpflichtet sich "
                  f"{who}, einmalig und kostenfrei einen geeigneten Ersatzkandidaten vorzuschlagen. Voraussetzung "
                  "ist, dass das Honorar vollständig bezahlt wurde. Die Garantie gilt nicht bei betriebsbedingter "
                  "Kündigung.", st["p"]),
        _heading("06", "Vertraulichkeit", st),
        Paragraph("Alle im Rahmen der Zusammenarbeit ausgetauschten Informationen – sowohl Unternehmensdaten als "
                  "auch personenbezogene Daten von Kandidaten – werden vertraulich behandelt. Diese Verpflichtung "
                  "besteht auch über das Ende der Zusammenarbeit hinaus.", st["p"]),
        _heading("07", "Gültigkeit ohne Unterschrift", st),
        Paragraph("Dieser Vertrag tritt auch ohne handschriftliche Unterschrift in Kraft. Es genügt, dass der "
                  f"Auftraggeber die Zusammenarbeit zu diesen Konditionen per E-Mail an {who} bestätigt.", st["p"]),
        _heading("08", "Sonstiges", st),
        *_bullets([
            "Änderungen oder Ergänzungen dieses Vertrags bedürfen der Schriftform.",
            f"Es gilt ausschließlich {escape(c['law'])}. Gerichtsstand ist der Sitz des beauftragenden Unternehmens.",
            "Sollten einzelne Bestimmungen dieses Vertrages unwirksam sein oder werden, bleibt die Wirksamkeit "
            "der übrigen Bestimmungen unberührt.",
            "Die Anlage „Abweichende Vereinbarungen“ (Seite 2) ist Bestandteil dieses Vertrags und geht "
            "abweichenden Regelungen oben vor." if annex else
            "Diese Vereinbarung bildet die Grundlage für eine vertrauensvolle und erfolgreiche Zusammenarbeit.",
        ], st),
    ]
    return left, right


def _box(html, st, width):
    t = Table([[Paragraph(html, st["p"])]], colWidths=[width])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PINK_BOX),
        ("LEFTPADDING", (0, 0), (-1, -1), 9), ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("ROUNDEDCORNERS", [6, 6, 6, 6]),
    ]))
    return t


def _signatures(cv, c, W, M, for_signature):
    gap = 22
    col_w = (W - 2 * M - gap) / 2
    y = 26
    for i, (name, sub) in enumerate([
        (c["contractor_signer"], "Auftragnehmerin, Ort, Datum"),
        (c["client_name"] + (f" – {c['client_signer']}" if c["client_signer"] else ""), "Auftraggeber, Ort, Datum"),
    ]):
        x = M + i * (col_w + gap)
        cv.setStrokeColor(TEXT)
        cv.setLineWidth(0.6)
        cv.line(x, y + 12, x + col_w, y + 12)
        cv.setFillColor(TEXT)
        _fit_string(cv, name, x, y, col_w, F["semibold"], 8.5)
        cv.setFillColor(GREY)
        cv.setFont(F["regular"], 7)
        cv.drawString(x, y - 11, sub)
        if i == 1 and for_signature:
            # Platzhalter: wird beim Hochladen zum Unterschriftsfeld (Documenso blendet ihn aus)
            cv.setFillColor(white)
            cv.setFont("Helvetica", 7)
            cv.drawString(x, y + 18, SIGNATURE_PLACEHOLDER)


SIGNATURE_PLACEHOLDER = "{{signature, r1}}"  # Documenso: Unterschriftsfeld für Empfänger 1


# --- Hilfen ---------------------------------------------------------------------------------------

def _spaced(text: str) -> str:
    return " ".join(text)


def _fit_string(cv, text, x, y, max_w, font, size):
    """Text in einer Zeile; bei Überlänge Schrift verkleinern (bis 70 %), danach kürzen."""
    s = size
    while pdfmetrics.stringWidth(text, font, s) > max_w and s > size * 0.7:
        s -= 0.25
    while pdfmetrics.stringWidth(text, font, s) > max_w and len(text) > 4:
        text = text[:-2].rstrip() + "…"
    cv.setFont(font, s)
    cv.drawString(x, y, text)


def _months(n: int) -> str:
    return f"{n} Monat" if n == 1 else f"{n} Monaten"


def _years(n: int) -> str:
    return f"{n} Jahr" if n == 1 else f"{n} Jahren"
