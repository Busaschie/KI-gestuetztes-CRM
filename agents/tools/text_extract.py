"""Text aus CV-Dateien lesen: PDF, Word (.docx), Textdateien. Scans werden erkannt und per OCR gelesen."""
import io
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
    pages = [(p.extract_text() or "") for p in reader.pages]
    text = "\n\n".join(pages).strip()
    if len(text) >= MIN_CHARS_PER_PAGE * max(len(pages), 1) / 2:
        return ExtractedText(text)
    if ocr is None:
        return ExtractedText(text, needs_ocr=True)
    return ExtractedText(ocr.ocr_pdf(data).strip(), ocr_used=True)


def _docx(data: bytes) -> str:
    import docx

    doc = docx.Document(io.BytesIO(data))
    parts = [p.text for p in doc.paragraphs]
    for table in doc.tables:  # viele CVs sind als Tabelle aufgebaut
        for row in table.rows:
            parts.append(" | ".join(c.text.strip() for c in row.cells))
    return "\n".join(t for t in parts if t.strip())
