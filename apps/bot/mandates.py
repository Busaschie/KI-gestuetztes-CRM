"""P1 Punkt 4: Neuer Auftrag per Sprache/Text → Vorschlag im Bot → Auftrag (+ Vertrag mit Stopp-Fenster).

Nie vollautomatisch: Sandra bestätigt mit einem Knopf; danach greift zusätzlich das Stopp-Fenster des Vertrags.
Unbekannte Firma → nur mit Namen anlegen (Vertragsdaten im Admin ergänzen); unbekannter Ansprechpartner → neu anlegen.
"""
from decimal import Decimal
from html import escape

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.clients.models import Contract, FeeModel
from apps.communications.models import InboundItem, Note
from apps.contacts.models import Company, Employment, Person
from apps.core.models import Origin
from apps.jobs.models import Mandate

from .extract import _similar, find_persons, person_label
from .models import BotDraft

MAX_COMPANIES = 5


# --- Erkennen und zuordnen ------------------------------------------------------------------------

def find_companies(name: str | None) -> list[Company]:
    if not name or len(name.strip()) < 2:
        return []
    pool = Company.objects.all()[:5000]
    scored = sorted(((max(_similar(name, c.name), _similar(name, c.name.split()[0])), c) for c in pool),
                    key=lambda x: -x[0])
    hits = [(s, c) for s, c in scored if s >= 0.75]
    if hits and (len(hits) == 1 or hits[0][0] - hits[1][0] >= 0.15):
        return [hits[0][1]]
    return [c for _, c in hits[:MAX_COMPANIES]]


def choose_fee_model(percent) -> tuple[FeeModel | None, str]:
    """Honorarmodell mit genau diesem Prozentsatz, sonst Standard. Abweichung als Text (braucht Freigabe)."""
    if percent is not None:
        exact = FeeModel.objects.filter(percent=Decimal(str(percent))).order_by("-is_default").first()
        if exact:
            return exact, ""
    model = FeeModel.objects.filter(is_default=True).first() or FeeModel.objects.order_by("pk").first()
    if model and percent is not None and Decimal(str(percent)) != model.percent:
        return model, f"Honorar {float(percent):g} % statt {float(model.percent):g} % ({model.name})"
    return model, ""


def prepare(draft: BotDraft) -> None:
    """Firma, Ansprechpartner und Honorarmodell zuordnen – Ergebnis in draft.data['m']."""
    d = draft.data
    companies = find_companies(d.get("company"))
    m = {"company_id": companies[0].pk if len(companies) == 1 else None,
         "company_candidates": [c.pk for c in companies] if len(companies) > 1 else [],
         "contact_id": None, "contact_candidates": [], "contact_new": None}
    company = companies[0] if len(companies) == 1 else None
    if d.get("person_name"):
        persons = find_persons(d["person_name"], company.name if company else d.get("company"))
        if len(persons) == 1:
            m["contact_id"] = persons[0].pk
        elif persons:
            m["contact_candidates"] = [p.pk for p in persons]
        else:
            m["contact_new"] = d["person_name"]
    elif company and company.signatory_id:
        m["contact_id"] = company.signatory_id
    fee, deviation = choose_fee_model(d.get("fee_percent"))
    m["fee_model_id"], m["deviation"] = (fee.pk if fee else None), deviation
    d["m"] = m
    draft.data = d
    draft.status = BotDraft.Status.AWAITING
    draft.save()


def _company(m):
    return Company.objects.filter(pk=m.get("company_id")).first() if m.get("company_id") else None


def _contact(m):
    return Person.objects.filter(pk=m.get("contact_id")).first() if m.get("contact_id") else None


def missing_for_contract(draft: BotDraft) -> list[str]:
    """Was fehlt, damit der Vertrag direkt raus kann (leer = sendbar)."""
    m, missing = draft.data["m"], []
    company, contact = _company(m), _contact(m)
    if not company:
        missing.append("Firmendaten (Firma neu – Adresse im Admin ergänzen)")
    elif not all([company.street, company.postal_code, company.city, company.country]):
        missing.append("Adresse der Firma")
    if not (contact and contact.email):
        missing.append("E-Mail des Unterzeichners")
    if not m.get("fee_model_id"):
        missing.append("Honorarmodell")
    if not draft.data.get("position"):
        missing.append("Position")
    if not settings.CONTRACTOR_NAME:
        missing.append("Daten der Auftragnehmerin (.env)")
    return missing


def needs_choice(m) -> bool:
    return bool(m.get("company_candidates") or m.get("contact_candidates"))


# --- Anzeige ---------------------------------------------------------------------------------------

def render(draft: BotDraft) -> tuple[str, list]:
    d, m, key = draft.data, draft.data["m"], f"d{draft.pk}"
    company, contact = _company(m), _contact(m)
    lines = ["🆕 <b>Neuer Auftrag</b>"]
    if company:
        lines.append(f"🏢 <b>Firma:</b> {escape(company.name)}")
    elif m.get("company_candidates"):
        lines.append(f"🏢 <b>Firma:</b> „{escape(d.get('company') or '')}“ – mehrere Treffer, bitte wählen:")
    else:
        lines.append(f"🏢 <b>Firma:</b> „{escape(d.get('company') or '?')}“ – neu, wird nur mit Namen angelegt")
    lines.append(f"💼 <b>Position:</b> {escape(d.get('position') or '– (fehlt)')}")
    if d.get("location"):
        lines.append(f"📍 <b>Ort:</b> {escape(d['location'])}")
    if contact:
        mail = escape(contact.email) if contact.email else "ohne E-Mail"
        lines.append(f"👤 <b>Ansprechpartner/Unterzeichner:</b> {escape(str(contact))} ({mail})")
    elif m.get("contact_candidates"):
        lines.append(f"👤 <b>Ansprechpartner:</b> „{escape(d.get('person_name') or '')}“ – mehrere Treffer, bitte wählen:")
    elif m.get("contact_new"):
        lines.append(f"👤 <b>Ansprechpartner:</b> „{escape(m['contact_new'])}“ – neu, wird angelegt (ohne E-Mail)")
    else:
        lines.append("👤 <b>Ansprechpartner:</b> keiner genannt")
    fee = FeeModel.objects.filter(pk=m.get("fee_model_id")).first()
    lines.append(f"💶 <b>Honorar:</b> {escape(fee.name) + f' ({float(fee.percent):g} %)' if fee else 'kein Honorarmodell'}")
    if m.get("deviation"):
        lines.append(f"⚠️ <b>Abweichung:</b> {escape(m['deviation'])}")

    buttons = []
    if m.get("company_candidates"):
        buttons += [[(f"🏢 {c.name}"[:60], f"{key}:c{c.pk}")]
                    for c in Company.objects.filter(pk__in=m["company_candidates"])]
    if m.get("contact_candidates"):
        by_id = {p.pk: p for p in Person.objects.filter(pk__in=m["contact_candidates"]).prefetch_related("employments__company")}
        buttons += [[(f"👤 {person_label(by_id[i])}"[:60], f"{key}:p{i}")] for i in m["contact_candidates"] if i in by_id]
    if not needs_choice(m):
        missing = missing_for_contract(draft)
        if missing:
            lines.append(f"\n📄 <b>Vertrag noch nicht sendbar</b> – fehlt: {escape(', '.join(missing))}")
        else:
            label = "✅ Abweichung freigeben + Vertrag senden" if m.get("deviation") else "✅ Auftrag + Vertrag senden"
            lines.append(f"\n📄 Vertrag geht nach Bestätigung mit {settings.CONTRACT_STOP_MINUTES} min Stopp-Fenster raus.")
            buttons.append([(label, f"{key}:ms")])
        buttons.append([("💾 Nur Auftrag anlegen", f"{key}:mo")])
    buttons.append([("🗑 Verwerfen + löschen", f"{key}:x")])
    return "\n".join(lines), buttons


# --- Knöpfe ---------------------------------------------------------------------------------------

def handle_action(draft: BotDraft, action: str, callback: dict, client) -> None:
    from .processing import _finish, _show, discard_draft

    m = draft.data["m"]
    if action.startswith("c") and action[1:].isdigit() and int(action[1:]) in m.get("company_candidates", []):
        m["company_id"], m["company_candidates"] = int(action[1:]), []
        _save_m(draft, m)
        client.answer_callback(callback["id"], "Firma gewählt")
        _show(draft, client)
    elif action.startswith("p") and action[1:].isdigit() and int(action[1:]) in m.get("contact_candidates", []):
        m["contact_id"], m["contact_candidates"] = int(action[1:]), []
        _save_m(draft, m)
        client.answer_callback(callback["id"], "Ansprechpartner gewählt")
        _show(draft, client)
    elif action in ("ms", "mo") and not needs_choice(m):
        send = action == "ms" and not missing_for_contract(draft)
        mandate, contract, result = save_mandate(draft, send_contract=send)
        client.answer_callback(callback["id"], "Gespeichert")
        _finish(draft, client, result)
    elif action == "x":
        discard_draft(draft, client, callback["message"].get("message_id"))
        client.answer_callback(callback["id"], "🗑 Verworfen – Nachricht gelöscht")
    else:
        client.answer_callback(callback["id"], "Bitte zuerst Firma/Ansprechpartner wählen" if needs_choice(m)
                               else "Unbekannte Aktion")


def _save_m(draft, m):
    draft.data = {**draft.data, "m": m}
    draft.save(update_fields=["data", "updated_at"])


# --- Speichern ------------------------------------------------------------------------------------

def _split_name(name: str) -> tuple[str, str]:
    parts = name.strip().split()
    for title in ("Herr", "Frau", "Hr.", "Fr.", "Dr."):
        if parts and parts[0] == title:
            parts = parts[1:]
    return (" ".join(parts[:-1]), parts[-1]) if len(parts) > 1 else ("", parts[0] if parts else "Unbekannt")


def save_mandate(draft: BotDraft, send_contract: bool) -> tuple[Mandate, Contract | None, str]:
    """Firma/Ansprechpartner (ggf. neu), Auftrag „Aktiv“, Vertragsentwurf; bei send_contract Versand mit Stopp-Fenster."""
    from apps.clients.services import ContractError, schedule_contract

    d, m, item = draft.data, draft.data["m"], draft.inbound
    with transaction.atomic():
        company = _company(m)
        if not company:
            company = Company.objects.create(name=(d.get("company") or "Unbekannte Firma")[:255], is_client=True)
        elif not company.is_client:
            company.is_client = True
            company.save(update_fields=["is_client", "updated_at"])
        contact = _contact(m)
        if not contact and m.get("contact_new"):
            first, last = _split_name(m["contact_new"])
            contact = Person.objects.create(first_name=first, last_name=last)
            Employment.objects.create(person=contact, company=company, origin=Origin.VOICE
                                      if item.channel == InboundItem.Channel.VOICE else Origin.MANUAL)
        mandate = Mandate.objects.create(
            company=company, contact_person=contact, title=(d.get("position") or "Position offen")[:255],
            location=(d.get("location") or "")[:255], status=Mandate.Status.ACTIVE,
        )
        contract = None
        fee = FeeModel.objects.filter(pk=m.get("fee_model_id")).first()
        if fee:
            percent = d.get("fee_percent")
            fee_percent = Decimal(str(percent)) if percent is not None and Decimal(str(percent)) != fee.percent else None
            contract = Contract.objects.create(  # abweichendes Honorar steht so im Vertrag, braucht Freigabe
                mandate=mandate, company=company, fee_model=fee, fee_percent=fee_percent,
                approved_at=timezone.now() if (send_contract and fee_percent is not None) else None,
            )
        if contact:
            Note.objects.create(person=contact, mandate=mandate, text=d.get("note") or "Neuer Auftrag",
                                origin=Origin.VOICE if item.channel == InboundItem.Channel.VOICE else Origin.MANUAL)
        item.person = contact
        item.status = InboundItem.Status.ASSIGNED
        item.processed_at = timezone.now()
        item.save(update_fields=["person", "status", "processed_at", "updated_at"])
        draft.person = contact
        draft.status = BotDraft.Status.SAVED
        draft.save(update_fields=["person", "status", "updated_at"])

    if not contract:
        return mandate, None, "💾 Auftrag angelegt – kein Honorarmodell, Vertrag bitte im Admin anlegen"
    if not send_contract:
        missing = missing_for_contract(draft)
        hint = f" Fehlt: {', '.join(missing)}." if missing else ""
        return mandate, contract, f"💾 Auftrag + Vertragsentwurf angelegt – Versand im Admin.{hint}"
    try:
        schedule_contract(contract)  # schickt selbst den Hinweis mit „Stoppen“
    except ContractError as e:
        return mandate, contract, f"💾 Auftrag angelegt, Vertrag <b>nicht</b> geplant: {escape(str(e))}"
    return mandate, contract, "✅ Auftrag angelegt, Vertrag geplant (Stopp im nächsten Hinweis möglich)"
