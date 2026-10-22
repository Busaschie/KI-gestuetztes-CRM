"""Mini App: Anmeldung über initData, Seite „Heute“, Aktionen."""
import hashlib
import hmac
import json
import time
from datetime import timedelta
from decimal import Decimal
from urllib.parse import urlencode

import pytest
from django.utils import timezone

from apps.clients.models import Contract, FeeModel
from apps.communications.models import FollowUp
from apps.contacts.models import Company, Person
from apps.jobs.models import Mandate
from apps.miniapp.auth import InitDataError, check_init_data

TOKEN = "123:ABC"
ME = 4711


def sign(user_id=ME, auth_date=None, token=TOKEN):
    data = {"auth_date": str(int(auth_date or time.time())), "query_id": "AAA",
            "user": json.dumps({"id": user_id, "first_name": "Sandra"})}
    check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    data["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(data)


@pytest.fixture(autouse=True)
def cfg(settings):
    settings.TELEGRAM_BOT_TOKEN = TOKEN
    settings.TELEGRAM_ALLOWED_CHAT_IDS = [ME]
    settings.MINIAPP_MAX_AGE_SECONDS = 3600
    settings.CONTACT_SUGGESTIONS_PER_DAY = 3


def hdr(**kw):
    return {"HTTP_X_TELEGRAM_INIT_DATA": sign(**kw)}


def test_check_init_data():
    assert check_init_data(sign(), TOKEN, 3600)["id"] == ME
    with pytest.raises(InitDataError, match="Signatur"):
        check_init_data(sign(token="999:XYZ"), TOKEN, 3600)
    with pytest.raises(InitDataError, match="abgelaufen"):
        check_init_data(sign(auth_date=time.time() - 7200), TOKEN, 3600)
    with pytest.raises(InitDataError):
        check_init_data("", TOKEN, 3600)


def test_shell_is_public_and_frameable(client):
    r = client.get("/tg/")
    assert r.status_code == 200 and "telegram-web-app.js" in r.content.decode()
    assert "frame-ancestors" in r["Content-Security-Policy"] and "X-Frame-Options" not in r


def test_today_requires_allowed_user(client, db):
    assert client.get("/tg/heute/").status_code == 403
    assert client.get("/tg/heute/", **hdr(user_id=999)).status_code == 403
    assert client.get("/tg/heute/", **hdr()).status_code == 200


def test_today_lists_and_actions(client, db):
    p = Person.objects.create(first_name="Eva", last_name="Meier")
    fu = FollowUp.objects.create(person=p, due_date=timezone.localdate(), text="Meier anrufen")
    care = FollowUp.objects.create(person=p, due_date=timezone.localdate(), text="Kontaktpflege: früherer Kunde",
                                   reason=FollowUp.Reason.RULE_6_MONTHS)
    company = Company.objects.create(name="Muster AG")
    m = Mandate.objects.create(company=company, title="CFO")
    c = Contract.objects.create(mandate=m, company=company, fee_model=FeeModel.objects.create(name="S", percent=Decimal(20)),
                                status=Contract.Status.SCHEDULED, scheduled_for=timezone.now() + timedelta(minutes=30))
    html = client.get("/tg/heute/", **hdr()).content.decode()
    assert "Meier anrufen" in html and "Kontaktpflege" in html and "Vertrag: " in html

    html = client.post(f"/tg/wv/{fu.pk}/week/", **hdr()).content.decode()
    fu.refresh_from_db()
    assert fu.due_date == timezone.localdate() + timedelta(days=7) and "Verschoben" in html

    client.post(f"/tg/wv/{care.pk}/done/", **hdr())
    care.refresh_from_db()
    p.refresh_from_db()
    assert care.done_at and p.last_contacted_at

    html = client.post(f"/tg/stopp/contract/{c.pk}/", **hdr()).content.decode()
    c.refresh_from_db()
    assert c.status == Contract.Status.DRAFT and "gestoppt" in html


def test_actions_need_post_and_auth(client, db):
    p = Person.objects.create(last_name="X")
    fu = FollowUp.objects.create(person=p, due_date=timezone.localdate(), text="x")
    assert client.post(f"/tg/wv/{fu.pk}/done/").status_code == 403
    assert client.get(f"/tg/wv/{fu.pk}/done/", **hdr()).status_code == 405


# --- Verträge ---------------------------------------------------------------------------------------

@pytest.fixture
def contract(db, settings):
    settings.SIGNATURE_PROVIDER = "fake"
    settings.CONTRACTOR_NAME = "Sandra Test SRL"
    settings.CONTRACT_STOP_MINUTES = 60
    company = Company.objects.create(name="Muster AG", street="Ring 1", postal_code="1010", city="Wien", country="AT")
    contact = Person.objects.create(first_name="Karl", last_name="Kunde", email="k@muster.example")
    m = Mandate.objects.create(company=company, contact_person=contact, title="Vertriebsleiter")
    return Contract.objects.create(mandate=m, company=company, fee_model=FeeModel.objects.create(name="S", percent=Decimal(20)))


def test_contracts_page_and_flow(client, contract, monkeypatch):
    monkeypatch.setattr("apps.clients.services.notify", lambda *a, **k: None)
    html = client.get("/tg/vertraege/", **hdr()).content.decode()
    assert "Entwürfe (1)" in html and "Vertriebsleiter – Muster AG" in html
    html = client.post(f"/tg/vertrag/{contract.pk}/send/", **hdr()).content.decode()
    contract.refresh_from_db()
    assert contract.status == Contract.Status.SCHEDULED and "Versand geplant" in html
    client.post(f"/tg/vertrag/{contract.pk}/stop/", **hdr())
    contract.refresh_from_db()
    assert contract.status == Contract.Status.DRAFT


def test_contract_status_transitions(client, contract):
    html = client.post(f"/tg/vertrag/{contract.pk}/paid/", **hdr()).content.decode()
    assert "Nicht möglich" in html  # Entwurf → Bezahlt verboten
    Contract.objects.filter(pk=contract.pk).update(status=Contract.Status.SIGNED)
    client.post(f"/tg/vertrag/{contract.pk}/invoice/", **hdr())
    client.post(f"/tg/vertrag/{contract.pk}/paid/", **hdr())
    contract.refresh_from_db()
    assert contract.status == Contract.Status.PAID
    assert contract.events.filter(message__contains="(Mini App)").count() == 2
    assert "Vertriebsleiter" not in client.get("/tg/vertraege/", **hdr()).content.decode()  # bezahlt = nicht mehr offen


# --- Aufträge ---------------------------------------------------------------------------------------

def test_mandates_and_candidate_actions(client, db):
    from apps.candidates.models import CandidateProfile
    from apps.pipeline.models import Submission

    company = Company.objects.create(name="Muster AG")
    m = Mandate.objects.create(company=company, title="CFO", status=Mandate.Status.ACTIVE)
    Mandate.objects.create(company=company, title="Alt", status=Mandate.Status.FILLED)
    p = Person.objects.create(first_name="Anna", last_name="Huber")
    sub = Submission.objects.create(candidate=CandidateProfile.objects.create(person=p), mandate=m)

    html = client.get("/tg/auftraege/", **hdr()).content.decode()
    assert "CFO – Muster AG" in html and "Alt –" not in html and "kein Vertrag" in html
    assert "Anna Huber" in client.get(f"/tg/auftrag/{m.pk}/", **hdr()).content.decode()

    client.post(f"/tg/kandidat/{sub.pk}/stage/", {"stage": "in_talks"}, **hdr())
    client.post(f"/tg/kandidat/{sub.pk}/spoken/", **hdr())
    client.post(f"/tg/kandidat/{sub.pk}/consent/", **hdr())
    sub.refresh_from_db()
    p.refresh_from_db()
    assert sub.stage == Submission.Stage.IN_TALKS and sub.spoken_with and sub.consent_to_present_at
    assert p.last_contacted_at
    html = client.post(f"/tg/kandidat/{sub.pk}/stage/", {"stage": "quatsch"}, **hdr()).content.decode()
    assert "Unbekannte Stufe" in html
