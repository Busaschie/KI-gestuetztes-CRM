from django.contrib import admin

from .models import Contract, FeeModel


@admin.register(FeeModel)
class FeeModelAdmin(admin.ModelAdmin):
    list_display = ["name", "percent", "is_default"]


@admin.register(Contract)
class ContractAdmin(admin.ModelAdmin):
    list_display = ["mandate", "company", "fee_model", "status", "sent_at", "signed_at"]
    list_filter = ["status"]
    autocomplete_fields = ["mandate", "company"]
