from django.contrib import admin, messages
from django.utils import timezone
from django.urls import reverse
from django.utils.html import format_html

from .models import Contract, ContractEvent, FeeModel
from .services import ContractError, schedule_contract, send_contract, stop_contract


@admin.register(FeeModel)
class FeeModelAdmin(admin.ModelAdmin):
    list_display = ["name", "percent", "is_default"]


class ContractEventInline(admin.TabularInline):
    model = ContractEvent
    extra = 0
    can_delete = False
    fields = ["created_at", "kind", "message"]
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Contract)
class ContractAdmin(admin.ModelAdmin):
    list_display = ["mandate", "company", "fee_model", "status", "scheduled_for", "sent_at", "reminders_sent", "signed_at"]
    list_filter = ["status"]
    autocomplete_fields = ["mandate", "company", "signer"]
    readonly_fields = [
        "preview_link", "draft_document", "approved_at", "scheduled_for", "signature_provider_id", "signing_link", "sent_at", "signed_at",
        "declined_at", "decline_reason", "reminders_sent", "last_reminder_at",
    ]
    fieldsets = [
        (None, {"fields": ["mandate", "company", "fee_model", "signer", "status", "preview_link", "draft_document"]}),
        ("Abweichungen", {"fields": ["deviations", "approved_at"]}),
        ("Unterschrift", {"fields": [
            "scheduled_for", "signature_provider_id", "signing_link", ("sent_at", "signed_at"),
            ("declined_at", "decline_reason"), ("reminders_sent", "last_reminder_at"), "document",
        ]}),
    ]
    inlines = [ContractEventInline]
    actions = ["action_send", "action_stop", "action_send_now", "action_approve"]

    @admin.display(description="Vertrag als PDF")
    def preview_link(self, obj):
        if not obj or not obj.pk:
            return "Nach dem Speichern verfügbar"
        url = reverse("clients:contract_preview", args=[obj.pk])
        return format_html('<a href="{}" target="_blank">📄 Vorschau öffnen</a>', url)

    @admin.display(description="Link zur Unterschrift")
    def signing_link(self, obj):
        return format_html('<a href="{}" target="_blank">{}</a>', obj.signing_url, obj.signing_url) if obj.signing_url else "–"

    @admin.action(description="Zur Unterschrift senden (mit Stopp-Fenster)")
    def action_send(self, request, queryset):
        for contract in queryset:
            try:
                schedule_contract(contract)
                if contract.scheduled_for:
                    when = timezone.localtime(contract.scheduled_for)
                    self.message_user(request, f"{contract}: Versand geplant für {when:%H:%M} (Stopp bis dahin möglich).",
                                      messages.SUCCESS)
                else:
                    self.message_user(request, f"{contract}: versendet.", messages.SUCCESS)
            except ContractError as e:
                self.message_user(request, f"{contract}: {e}", messages.ERROR)

    @admin.action(description="Geplanten Versand stoppen")
    def action_stop(self, request, queryset):
        for contract in queryset:
            try:
                stop_contract(contract)
                self.message_user(request, f"{contract}: gestoppt.", messages.SUCCESS)
            except ContractError as e:
                self.message_user(request, f"{contract}: {e}", messages.ERROR)

    @admin.action(description="Sofort senden (ohne Stopp-Fenster)")
    def action_send_now(self, request, queryset):
        for contract in queryset:
            try:
                send_contract(contract)
                self.message_user(request, f"{contract}: versendet.", messages.SUCCESS)
            except ContractError as e:
                self.message_user(request, f"{contract}: {e}", messages.ERROR)

    @admin.action(description="Abweichungen freigeben")
    def action_approve(self, request, queryset):
        n = queryset.filter(approved_at__isnull=True).exclude(deviations="").update(approved_at=timezone.now())
        self.message_user(request, f"{n} Vertrag/Verträge freigegeben.", messages.SUCCESS)
