"""Für Tests und Entwicklung ohne DocuSeal-Konto."""
import itertools

from .base import SignatureProvider, SubmissionResult

_ids = itertools.count(1)


class FakeSignatureProvider(SignatureProvider):
    calls: list[dict] = []

    def create_submission(self, **kwargs):
        FakeSignatureProvider.calls.append(kwargs)
        n = next(_ids)
        return SubmissionResult(submission_id=f"fake-{n}", signing_url=f"https://sign.example/s/fake-{n}")

    def download(self, url):
        return b"%PDF-1.4 fake signed contract"
