"""Für Tests und Entwicklung ohne DocuSeal-Konto."""
import itertools

from django.utils import timezone

from .base import SignatureProvider, SubmissionResult

_ids = itertools.count(1)


def _minimal_pdf(lines: list[str]) -> bytes:
    """Einseitiges, gültiges PDF ohne Zusatzbibliothek (nur für den Fake)."""
    def esc(t):
        return t.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    text = "BT /F1 14 Tf 72 760 Td 20 TL " + " ".join(f"({esc(line)}) Tj T*" for line in lines) + " ET"
    stream = text.encode("cp1252", "replace")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for i, obj in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + obj + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)


class FakeSignatureProvider(SignatureProvider):
    calls: list[dict] = []

    def create_submission(self, **kwargs):
        FakeSignatureProvider.calls.append(kwargs)
        n = next(_ids)
        return SubmissionResult(submission_id=f"fake-{n}", signing_url=f"https://sign.example/s/fake-{n}",
                                submitter_id=f"fake-sub-{n}")

    reminded: list[str] = []

    def remind(self, submitter_id):
        FakeSignatureProvider.reminded.append(submitter_id)

    def download(self, url):
        return _minimal_pdf([
            "TESTVERTRAG (Fake-Signatur)",
            "Kein echter Vertrag - erzeugt ohne DocuSeal.",
            f"Unterschrieben (simuliert): {timezone.localtime():%d.%m.%Y %H:%M}",
        ])
