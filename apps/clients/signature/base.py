from dataclasses import dataclass


class SignatureError(Exception):
    pass


@dataclass
class SubmissionResult:
    submission_id: str
    signing_url: str = ""


class SignatureProvider:
    def create_submission(self, *, template_id: str, role: str, signer_name: str, signer_email: str,
                          values: dict, external_id: str) -> SubmissionResult:
        raise NotImplementedError

    def download(self, url: str) -> bytes:
        raise NotImplementedError
