"""DocuSeal (Cloud EU: https://api.docuseal.eu, selbst gehostet: https://<host>/api)."""
import httpx

from .base import SignatureError, SignatureProvider, SubmissionResult


class DocuSealProvider(SignatureProvider):
    def __init__(self, api_url: str, api_key: str, timeout: float = 30):
        if not api_key:
            raise SignatureError("DOCUSEAL_API_KEY fehlt in der .env")
        self.api_url = api_url.rstrip("/")
        self.headers = {"X-Auth-Token": api_key}
        self.timeout = timeout

    def create_submission(self, *, template_id, role, signer_name, signer_email, values, external_id):
        body = {
            "template_id": int(template_id),
            "send_email": True,
            "submitters": [{
                "role": role, "name": signer_name, "email": signer_email,
                "external_id": external_id, "values": values,
            }],
        }
        try:
            resp = httpx.post(f"{self.api_url}/submissions", json=body, headers=self.headers, timeout=self.timeout)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise SignatureError(f"DocuSeal {e.response.status_code}: {e.response.text[:300]}") from e
        except httpx.HTTPError as e:
            raise SignatureError(f"DocuSeal nicht erreichbar: {e}") from e
        submitters = resp.json()
        if not isinstance(submitters, list) or not submitters:
            raise SignatureError(f"Unerwartete Antwort von DocuSeal: {str(submitters)[:300]}")
        first = submitters[0]
        return SubmissionResult(submission_id=str(first["submission_id"]), signing_url=first.get("embed_src") or "",
                                submitter_id=str(first.get("id") or ""))

    def remind(self, submitter_id):
        """PUT /submitters/{id} mit send_email=true – DocuSeal schickt die Einladung erneut."""
        if not submitter_id:
            raise SignatureError("Keine Unterzeichner-ID gespeichert – Erinnerung nicht möglich")
        try:
            resp = httpx.put(f"{self.api_url}/submitters/{submitter_id}", json={"send_email": True},
                             headers=self.headers, timeout=self.timeout)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise SignatureError(f"DocuSeal {e.response.status_code}: {e.response.text[:300]}") from e
        except httpx.HTTPError as e:
            raise SignatureError(f"DocuSeal nicht erreichbar: {e}") from e

    def download(self, url):
        try:
            resp = httpx.get(url, headers=self.headers, timeout=self.timeout, follow_redirects=True)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise SignatureError(f"Download des Vertrags fehlgeschlagen: {e}") from e
        return resp.content
