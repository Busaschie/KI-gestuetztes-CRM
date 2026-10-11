from django.contrib import admin, messages
from django.utils import timezone
from django.utils.html import format_html

from .models import Contract, ContractEvent, FeeModel
from .services import ContractError, send_contract


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
    list_display = ["mandate", "company", "fee_model", "status", "sent_at", "signed_at"]
    list_filter = ["status"]
    autocomplete_fields = ["mandate", "company", "signer"]
    readonly_fields = [
        "approved_at", "signature_provider_id", "signing_link", "sent_at", "signed_at",
        "declined_at", "decline_reason", "reminders_sent",
    ]
    fieldsets = [
        (None, {"fields": ["mandate", "company", "fee_model", "signer", "status"]}),
        ("Abweichungen", {"fields": ["deviations", "approved_at"]}),
        ("Unterschrift", {"fields": [
            "signature_provider_id", "signing_link", ("sent_at", "signed_at"),
            ("declined_at", "decline_reason"), "reminders_sent", "document",
        ]}),
    ]
    inlines = [ContractEventInline]
    actions = ["action_send", "action_approve"]

    @admin.display(description="Link zur Unterschrift")
    def signing_link(self, obj):
        return format_html('<a href="{}" target="_blank">{}</a>', obj.signing_url, obj.signing_url) if obj.signing_url else "–"

    @admin.action(description="Zur Unterschrift senden (DocuSeal)")
    def action_send(self, request, queryset):
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
