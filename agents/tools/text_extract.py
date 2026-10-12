"""Text aus CV-Dateien lesen: PDF, Word (.docx), Textdateien. Scans werden erkannt und per OCR gelesen."""
import io
import re
from dataclasses import dataclass
from pathlib import Path

MIN_CHARS_PER_PAGE = 80  # darunter gilt ein PDF als Scan


class UnsupportedFile(ValueError):
    pass


@dataclass
class ExtractedText:
    text: str
    ocr_used: bool = False
    needs_ocr: bool = False  # Scan erkannt, aber kein OCR verfügbar


def extract_text(filename: str, data: bytes, ocr=None) -> ExtractedText:
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        return _pdf(data, ocr)
    if ext == ".docx":
        return ExtractedText(_docx(data))
    if ext in (".txt", ".md"):
        return ExtractedText(data.decode("utf-8", errors="replace"))
    if ext == ".doc":
        raise UnsupportedFile("Altes Word-Format (.doc) – bitte als .docx oder PDF speichern")
    raise UnsupportedFile(f"Dateityp {ext or '(ohne Endung)'} wird nicht unterstützt")


def _pdf(data: bytes, ocr) -> ExtractedText:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    n_pages = max(len(reader.pages), 1)
    fallback = "\n\n".join((p.extract_text() or "") for p in reader.pages).strip()
    # pdfminer liest nach Position auf der Seite (sichtbare Reihenfolge, Spalten getrennt);
    # pypdf liest in Speicherreihenfolge, die bei manchen Erstellern verwürfelt ist → nur Rückfall
    text = _pdfminer(data)
    if len(text) < 0.7 * len(fallback):
        text = fallback
    if len(text) >= MIN_CHARS_PER_PAGE * n_pages / 2:
        return ExtractedText(text)
    if ocr is None:
        return ExtractedText(text, needs_ocr=True)
    return ExtractedText(ocr.ocr_pdf(data).strip(), ocr_used=True)


_CID_BULLET = re.compile(r"^(\s*)\(cid:\d+\)\s*", re.M)
_CID = re.compile(r"\(cid:\d+\)")


_DATE_ONLY = re.compile(
    r"^\s*(?:(?:seit|since|din|from)\s+)?[\w./ ]{0,12}(?:19|20)\d{2}"
    r"(?:\s*(?:–|—|-|bis|to)\s*[\w./ ]{0,20})?\s*$", re.I)


def _pdfminer(data: bytes) -> str:
    try:
        from pdfminer.high_level import extract_pages
        from pdfminer.layout import LAParams, LTTextBox, LTTextLine

        pages = list(extract_pages(io.BytesIO(data), laparams=LAParams()))
    except Exception:  # defektes PDF o. Ä. → pypdf übernimmt
        return ""
    out = []
    for page in pages:
        lines = []  # (box_nr, line) in pdfminer-Reihenfolge (sichtbar, Spalten getrennt)
        for nr, box in enumerate(el for el in page if isinstance(el, LTTextBox)):
            lines += [(nr, ln) for ln in box if isinstance(ln, LTTextLine)]
        texts = {id(ln): ln.get_text().strip() for _, ln in lines}
        # Rechtsbündiger Zeitraum ("Titel ........ 2012 – 2017") wird von pdfminer als eigener Block
        # gelesen → an die Zeile auf gleicher Höhe links davon anhängen
        # Nicht bei Zeiträumen am linken Rand einer Spalte (dort beginnen auch andere Zeilen) –
        # sonst würde der Zeitraum an die Seitenleiste daneben gehängt
        margins = [ln.x0 for _, ln in lines if not _DATE_ONLY.match(texts[id(ln)])]
        merged = set()
        for _, ln in lines:
            t = texts[id(ln)]
            if not _DATE_ONLY.match(t) or sum(abs(x - ln.x0) < 2 for x in margins) >= 2:
                continue
            left = [o for _, o in lines if o is not ln and id(o) not in merged and o.x1 <= ln.x0 + 1
                    and abs((o.y0 + o.y1) / 2 - (ln.y0 + ln.y1) / 2) < max(ln.height, 1) * 0.6]
            if left:
                target = max(left, key=lambda o: o.x1)
                texts[id(target)] = f"{texts[id(target)]} {t}"
                merged.add(id(ln))
        prev = None
        for nr, ln in lines:
            if id(ln) in merged:
                continue
            if prev is not None and nr != prev:
                out.append("")
            out.append(texts[id(ln)])
            prev = nr
        out.append("")
    raw = "\n".join(out)
    raw = _CID_BULLET.sub(r"\1• ", raw)  # nicht abbildbare Aufzählungszeichen
    raw = _CID.sub("", raw)
    return re.sub(r"\n{3,}", "\n\n", raw).strip()


def _docx(data: bytes) -> str:
    import docx

    doc = docx.Document(io.BytesIO(data))
    parts = [p.text for p in doc.paragraphs]
    for table in doc.tables:  # viele CVs sind als Tabelle aufgebaut
        for row in table.rows:
            parts.append(" | ".join(c.text.strip() for c in row.cells))
    return "\n".join(t for t in parts if t.strip())
