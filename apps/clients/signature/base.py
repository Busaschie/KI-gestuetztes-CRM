from dataclasses import dataclass


class SignatureError(Exception):
    pass


@dataclass
class SubmissionResult:
    submission_id: str
    signing_url: str = ""
    submitter_id: str = ""


class SignatureProvider:
    def create_submission_from_pdf(self, *, pdf: bytes, name: str, signer_name: str, signer_email: str,
                                   external_id: str) -> SubmissionResult:
        """Eigenes PDF zur Unterschrift senden; das Unterschriftsfeld steht als Platzhalter im PDF."""
        raise NotImplementedError

    def download(self, ref: str) -> bytes:
        raise NotImplementedError

    def remind(self, submitter_id: str, submission_id: str = "") -> None:
        """Signatur-Einladung an den Unterzeichner erneut senden."""
        raise NotImplementedError
