"""Telegram Mini App – mobile Oberfläche für Sandra (B-032). Etappe a: Grundgerüst + Seite „Heute“.

Die Hülle (/tg/) ist statisch; alle Daten kommen als Fragmente über htmx mit initData-Header (auth.tg_required).
Aktionen nutzen dieselbe Logik wie Bot und Admin (Stoppen, Erledigt, Verschieben) – nichts doppelt.
"""
from django.conf import settings
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.decorators.http import require_POST

from apps.clients.models import Contract, ContractEvent
from apps.clients.services import ContractError, schedule_contract, send_contract, stop_contract
from apps.communications.contact_care import CARE_REASONS, mark_done, opt_out, postpone, suggestions
from apps.communications.models import FollowUp, InboundItem, OutboundMessage
from apps.communications.services import MessageError, stop_message

from .auth import tg_required

FRAME_ANCESTORS = "frame-ancestors https://web.telegram.org https://*.telegram.org"


def _frameable(response):
    """Telegram Web bettet die Mini App in einen iframe ein – nur dort erlauben."""
    response["Content-Security-Policy"] = FRAME_ANCESTORS
    return response


@xframe_options_exempt
def shell(request):
    return _frameable(render(request, "miniapp/shell.html"))


def _today_context(message: str = "") -> dict:
    today = timezone.localdate()
    due = list(FollowUp.objects.filter(done_at__isnull=True, due_date__lte=today).exclude(reason__in=CARE_REASONS)
               .select_related("person", "mandate").order_by("due_date")[:30])
    care = list(suggestions(today)[:settings.CONTACT_SUGGESTIONS_PER_DAY])
    contracts = list(Contract.objects.filter(status=Contract.Status.SCHEDULED)
                     .select_related("mandate__company").order_by("scheduled_for"))
    messages = list(OutboundMessage.objects.filter(status=OutboundMessage.Status.SCHEDULED)
                    .select_related("recipient").order_by("scheduled_for"))
    unassigned = InboundItem.objects.filter(status__in=(InboundItem.Status.UNASSIGNED, InboundItem.Status.NEEDS_QUESTION,
                                                        InboundItem.Status.FAILED)).count()
    return {"today": today, "due": due, "care": care, "contracts": contracts, "out_messages": messages,
            "scheduled_count": len(contracts) + len(messages), "unassigned": unassigned, "message": message}


@xframe_options_exempt
@tg_required
def today(request):
    return _frameable(render(request, "miniapp/today.html", _today_context()))


@xframe_options_exempt
@tg_required
@require_POST
def followup_action(request, pk: int, action: str):
    fu = get_object_or_404(FollowUp, pk=pk, done_at__isnull=True)
    if action == "done":
        mark_done(fu)
        msg = f"✅ Erledigt: {fu.person or fu.text[:40]}"
    elif action == "week":
        postpone(fu, 7)
        msg = f"⏭ Verschoben auf {fu.due_date:%d.%m.}"
    elif action == "month":
        postpone(fu, 30)
        msg = f"⏭ Verschoben auf {fu.due_date:%d.%m.}"
    elif action == "off" and fu.reason in CARE_REASONS:
        opt_out(fu)
        msg = f"🚫 Keine Kontaktpflege mehr: {fu.person}"
    else:
        msg = "Unbekannte Aktion"
    return _frameable(render(request, "miniapp/today.html", _today_context(msg)))


@xframe_options_exempt
@tg_required
@require_POST
def stop_action(request, kind: str, pk: int):
    try:
        if kind == "contract":
            contract = stop_contract(get_object_or_404(Contract, pk=pk))
            msg = f"⛔ Vertrag gestoppt: {contract.mandate}"
        elif kind == "message":
            out = stop_message(get_object_or_404(OutboundMessage, pk=pk))
            msg = f"⛔ Versand gestoppt: {out.subject}"
        else:
            msg = "Unbekannte Aktion"
    except (ContractError, MessageError) as e:
        msg = f"⚠️ {e}"
    return _frameable(render(request, "miniapp/today.html", _today_context(msg)))


# --- Verträge (Etappe b) ----------------------------------------------------------------------------

CONTRACT_GROUPS = [
    ("Entwürfe", (Contract.Status.DRAFT,)),
    ("Geplant – Stopp möglich", (Contract.Status.SCHEDULED,)),
    ("Warten auf Unterschrift", (Contract.Status.SENT, Contract.Status.PENDING)),
    ("Unterschrieben", (Contract.Status.SIGNED,)),
    ("Rechnung fällig", (Contract.Status.INVOICE_DUE,)),
]
STATUS_TARGETS = {  # wie im Bot und im Admin: nur sinnvolle Übergänge
    "invoice": (Contract.Status.INVOICE_DUE, (Contract.Status.SIGNED,)),
    "paid": (Contract.Status.PAID, (Contract.Status.SIGNED, Contract.Status.INVOICE_DUE)),
}


def _contracts_context(message: str = "") -> dict:
    qs = (Contract.objects.filter(status__in=[s for _, group in CONTRACT_GROUPS for s in group])
          .select_related("mandate__company", "fee_model", "signer", "mandate__contact_person")
          .order_by("-updated_at"))
    contracts = list(qs)
    groups = [(title, [c for c in contracts if c.status in states]) for title, states in CONTRACT_GROUPS]
    return {"groups": groups, "message": message, "stop_minutes": settings.CONTRACT_STOP_MINUTES}


@xframe_options_exempt
@tg_required
def contracts(request):
    return _frameable(render(request, "miniapp/contracts.html", _contracts_context()))


@xframe_options_exempt
@tg_required
@require_POST
def contract_action(request, pk: int, action: str):
    contract = get_object_or_404(Contract.objects.select_related("mandate"), pk=pk)
    try:
        if action == "send":
            schedule_contract(contract)
            msg = (f"📄 Versand geplant um {timezone.localtime(contract.scheduled_for):%H:%M}: {contract.mandate}"
                   if contract.scheduled_for else f"📤 Versendet: {contract.mandate}")
        elif action == "stop":
            stop_contract(contract)
            msg = f"⛔ Gestoppt – wieder Entwurf: {contract.mandate}"
        elif action == "now":
            send_contract(contract)
            msg = f"📤 Versendet: {contract.mandate}"
        elif action in STATUS_TARGETS:
            target, allowed = STATUS_TARGETS[action]
            if contract.status not in allowed:
                raise ContractError(f"Nicht möglich (Status {contract.get_status_display()}).")
            before = contract.get_status_display()
            contract.status = target
            contract.save(update_fields=["status", "updated_at"])
            ContractEvent.objects.create(contract=contract, kind="status",
                                         message=f"{before} → {contract.get_status_display()} (Mini App)")
            msg = f"✅ {contract.mandate}: {contract.get_status_display()}"
        else:
            msg = "Unbekannte Aktion"
    except ContractError as e:
        msg = f"⚠️ {e}"
    return _frameable(render(request, "miniapp/contracts.html", _contracts_context(msg)))


# --- Aufträge und Kandidaten (Etappe c) -------------------------------------------------------------

OPEN_MANDATES = ("active", "on_hold", "draft")


def _mandates_context(message: str = "") -> dict:
    from django.db.models import Count

    from apps.jobs.models import Mandate

    mandates = list(Mandate.objects.filter(status__in=OPEN_MANDATES).select_related("company", "contact_person")
                    .annotate(n=Count("submissions")).order_by("status", "-updated_at"))
    for m in mandates:
        m.contract_label = ("✅ Vertrag unterschrieben" if m.has_signed_contract else
                            "📄 Vertrag offen" if m.contracts.exclude(status=Contract.Status.CANCELLED).exists()
                            else "⚠️ kein Vertrag")
    return {"mandates": mandates, "message": message}


@xframe_options_exempt
@tg_required
def mandates(request):
    return _frameable(render(request, "miniapp/mandates.html", _mandates_context()))


def _mandate_context(pk: int, message: str = "") -> dict:
    from apps.jobs.models import Mandate
    from apps.pipeline.models import Submission

    mandate = get_object_or_404(Mandate.objects.select_related("company", "contact_person"), pk=pk)
    subs = list(Submission.objects.filter(mandate=mandate).select_related("candidate__person")
                .order_by("stage", "candidate__person__last_name"))
    return {"mandate": mandate, "subs": subs, "stages": Submission.Stage.choices, "message": message}


@xframe_options_exempt
@tg_required
def mandate_detail(request, pk: int):
    return _frameable(render(request, "miniapp/mandate.html", _mandate_context(pk)))


@xframe_options_exempt
@tg_required
@require_POST
def submission_action(request, pk: int, action: str):
    from apps.communications.models import mark_contacted
    from apps.pipeline.models import Submission

    sub = get_object_or_404(Submission.objects.select_related("candidate__person"), pk=pk)
    name = sub.candidate.person
    if action == "stage":
        stage = request.POST.get("stage", "")
        if stage not in Submission.Stage.values:
            msg = "Unbekannte Stufe"
        else:
            sub.stage = stage
            sub.save(update_fields=["stage", "updated_at"])
            msg = f"✅ {name}: {sub.get_stage_display()}"
    elif action == "spoken":
        sub.spoken_with = not sub.spoken_with
        sub.save(update_fields=["spoken_with", "updated_at"])
        if sub.spoken_with:
            mark_contacted(sub.candidate.person_id)
        msg = f"✅ {name}: {'persönlich gesprochen' if sub.spoken_with else 'nicht gesprochen'}"
    elif action == "consent" and not sub.consent_to_present_at:
        sub.consent_to_present_at = timezone.now()
        sub.save(update_fields=["consent_to_present_at", "updated_at"])
        msg = f"✅ Zustimmung dokumentiert: {name}"
    else:
        msg = "Nicht möglich"
    return _frameable(render(request, "miniapp/mandate.html", _mandate_context(sub.mandate_id, msg)))
