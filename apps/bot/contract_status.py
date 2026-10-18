"""Vertragsstatus per Sprache/Text (P1 Punkt 4): „Muster AG hat bezahlt“, „Rechnung an Muster AG ist raus“.

Nur unterschriebene Verträge; Übergänge: Unterschrieben → Rechnung fällig → Bezahlt (Unterschrieben → Bezahlt erlaubt).
Mit Bestätigung im Bot und Eintrag im Vertragsprotokoll.
"""
from html import escape

from django.db import transaction
from django.utils import timezone

from apps.clients.models import Contract, ContractEvent
from apps.communications.models import InboundItem

from .extract import _similar
from .mandates import find_companies
from .models import BotDraft

ALLOWED_FROM = {
    Contract.Status.INVOICE_DUE: (Contract.Status.SIGNED,),
    Contract.Status.PAID: (Contract.Status.SIGNED, Contract.Status.INVOICE_DUE),
}
MAX = 5


def find_contracts(company: str | None, position: str | None, target: str) -> list[Contract]:
    companies = find_companies(company)
    if not companies:
        return []
    qs = (Contract.objects.filter(company__in=companies, status__in=ALLOWED_FROM[target])
          .select_related("mandate", "company").order_by("-signed_at", "-pk"))
    contracts = list(qs[:20])
    if position and len(contracts) > 1:
        matching = [c for c in contracts if position.casefold() in c.mandate.title.casefold()
                    or _similar(position, c.mandate.title) >= 0.6]
        contracts = matching or contracts
    return contracts[:MAX]


def prepare(draft: BotDraft) -> None:
    d = draft.data
    contracts = find_contracts(d.get("company"), d.get("position"), d["contract_status"])
    d["s"] = {"contract_id": contracts[0].pk if len(contracts) == 1 else None,
              "contract_candidates": [c.pk for c in contracts] if len(contracts) > 1 else []}
    draft.data, draft.status = d, BotDraft.Status.AWAITING
    draft.save()


def _label(target) -> str:
    return Contract.Status(target).label


def render(draft: BotDraft) -> tuple[str, list]:
    d, s, key = draft.data, draft.data["s"], f"d{draft.pk}"
    target = d["contract_status"]
    lines = [f"📄 <b>Vertragsstatus → {escape(_label(target))}</b>"]
    contract = Contract.objects.select_related("mandate").filter(pk=s.get("contract_id")).first() if s.get("contract_id") else None
    buttons = []
    if contract:
        lines.append(f"Vertrag: {escape(str(contract.mandate))} (bisher: {escape(contract.get_status_display())})")
        buttons.append([(f"✅ Auf „{_label(target)}“ setzen", f"{key}:ok")])
    elif s.get("contract_candidates"):
        lines.append("Mehrere passende Verträge, bitte wählen:")
        buttons += [[(f"📄 {c.mandate}"[:60], f"{key}:v{c.pk}")]
                    for c in Contract.objects.select_related("mandate").filter(pk__in=s["contract_candidates"])]
    else:
        what = " ".join(x for x in (d.get("company"), d.get("position")) if x) or "?"
        lines.append(f"Kein passender unterschriebener Vertrag für „{escape(what)}“ gefunden.")
    buttons.append([("🗑 Verwerfen + löschen", f"{key}:x")])
    return "\n".join(lines), buttons


def handle_action(draft: BotDraft, action: str, callback: dict, client) -> None:
    from .processing import _finish, _show, discard_draft

    s = draft.data["s"]
    if action.startswith("v") and action[1:].isdigit() and int(action[1:]) in s.get("contract_candidates", []):
        s["contract_id"], s["contract_candidates"] = int(action[1:]), []
        draft.data = {**draft.data, "s": s}
        draft.save(update_fields=["data", "updated_at"])
        client.answer_callback(callback["id"], "Vertrag gewählt")
        _show(draft, client)
    elif action == "ok" and s.get("contract_id"):
        contract = set_status(draft)
        if contract is None:
            client.answer_callback(callback["id"], "Nicht möglich (Status hat sich geändert)")
            return
        client.answer_callback(callback["id"], "Gespeichert")
        _finish(draft, client, f"✅ {escape(str(contract.mandate))}: {escape(contract.get_status_display())}")
    elif action == "x":
        discard_draft(draft, client, callback["message"].get("message_id"))
        client.answer_callback(callback["id"], "🗑 Verworfen – Nachricht gelöscht")
    else:
        client.answer_callback(callback["id"], "Nicht möglich")


@transaction.atomic
def set_status(draft: BotDraft) -> Contract | None:
    target = draft.data["contract_status"]
    contract = Contract.objects.select_for_update().select_related("mandate").get(pk=draft.data["s"]["contract_id"])
    if contract.status not in ALLOWED_FROM[target]:
        return None
    before = contract.get_status_display()
    contract.status = target
    contract.save(update_fields=["status", "updated_at"])
    ContractEvent.objects.create(contract=contract, kind="status",
                                 message=f"{before} → {contract.get_status_display()} (per Telegram)")
    item = draft.inbound
    item.status, item.processed_at = InboundItem.Status.ASSIGNED, timezone.now()
    item.save(update_fields=["status", "processed_at", "updated_at"])
    draft.status = BotDraft.Status.SAVED
    draft.save(update_fields=["status", "updated_at"])
    return contract
