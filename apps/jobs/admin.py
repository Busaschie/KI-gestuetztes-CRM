from django.contrib import admin

from .models import Mandate


@admin.register(Mandate)
class MandateAdmin(admin.ModelAdmin):
    list_display = ["title", "company", "status", "has_signed_contract", "created_at"]
    list_filter = ["status"]
    search_fields = ["title", "company__name"]
    autocomplete_fields = ["company", "contact_person", "origin_person"]

    @admin.display(boolean=True, description="Vertrag unterschrieben")
    def has_signed_contract(self, obj):
        return obj.has_signed_contract
