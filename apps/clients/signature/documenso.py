"""Documenso (Open Source, Community Edition selbst gehostet) – API v2 „Envelopes“.

Unser Vertrags-PDF enthält den Platzhalter {{signature, r1}}; Documenso erkennt ihn beim Hochladen und
legt dort das Unterschriftsfeld für Empfänger 1 an. Stand 17.10.2026 nach Doku umgesetzt, im Test zu prüfen:
Erinnerung (/envelope/redistribute) und Download (/envelope/item/{id}/download) stehen nur im Quellcode, nicht in der Doku.
"""
import json

import httpx

from .base import SignatureError, SignatureProvider, SubmissionResult

PLACEHOLDER = "{{signature, r1}}"


class DocumensoProvider(SignatureProvider):
    def __init__(self, api_url: str, api_key: str, timeout: float = 60):
        if not api_key:
            raise SignatureError("DOCUMENSO_API_KEY fehlt in der .env")
        self.api_url = api_url.rstrip("/")
        self.headers = {"Authorization": api_key}
        self.timeout = timeout

    def _request(self, method, path, **kwargs):
        try:
            resp = httpx.request(method, f"{self.api_url}{path}", headers=self.headers, timeout=self.timeout, **kwargs)
        except httpx.HTTPError as e:
            raise SignatureError(f"Documenso nicht erreichbar: {e}") from e
        if resp.status_code >= 400:
            raise SignatureError(f"Documenso {resp.status_code}: {resp.text[:300]}")
        return resp

    def create_submission(self, **kwargs):
        raise SignatureError("Documenso arbeitet mit eigenem PDF – CONTRACT_SOURCE=pdf setzen")

    def create_submission_from_pdf(self, *, pdf, name, role, signer_name, signer_email, external_id):
        payload = {
            "type": "DOCUMENT",
            "title": name,
            "externalId": external_id,
            "recipients": [{"email": signer_email, "name": signer_name, "role": "SIGNER"}],
        }
        created = self._request(
            "POST", "/envelope/create",
            data={"payload": json.dumps(payload)},
            files={"files": (f"{external_id}.pdf", pdf, "application/pdf")},
        ).json()
        envelope_id = created.get("id")
        if not envelope_id:
            raise SignatureError(f"Unerwartete Antwort von Documenso: {str(created)[:300]}")
        sent = self._request("POST", "/envelope/distribute", json={"envelopeId": envelope_id}).json()
        recipients = sent.get("recipients") or []
        first = recipients[0] if recipients else {}
        return SubmissionResult(submission_id=str(envelope_id), signing_url=first.get("signingUrl") or "",
                                submitter_id=str(first.get("id") or ""))

    def remind(self, submitter_id, submission_id=""):
        """POST /envelope/redistribute – laut Quellcode (envelope-router/redistribute-envelope.types.ts):
        schickt die Einladung erneut an Empfänger, die noch nicht unterschrieben haben, und verlängert den Link."""
        if not (submitter_id and submission_id and str(submitter_id).isdigit()):
            raise SignatureError("Documenso: Envelope- oder Empfänger-ID fehlt – Erinnerung nicht möglich")
        self._request("POST", "/envelope/redistribute",
                      json={"envelopeId": submission_id, "recipients": [int(submitter_id)]})

    def download(self, ref):
        """ref = „envelope:<id>“ → unterschriebenes PDF holen. Endpunkt laut Doku ungeklärt – im Test prüfen."""
        if not ref.startswith("envelope:"):
            raise SignatureError(f"Unbekannter Download-Verweis: {ref}")
        envelope_id = ref.split(":", 1)[1]
        envelope = self._request("GET", f"/envelope/{envelope_id}").json()
        items = envelope.get("envelopeItems") or []
        if not items:
            raise SignatureError("Documenso: keine Datei im Envelope gefunden")
        resp = self._request("GET", f"/envelope/item/{items[0]['id']}/download")
        if resp.headers.get("content-type", "").startswith("application/json"):
            url = resp.json().get("downloadUrl") or resp.json().get("url")
            if not url:
                raise SignatureError(f"Documenso: kein Download-Link ({resp.text[:200]})")
            return httpx.get(url, timeout=self.timeout).content
        return resp.content
