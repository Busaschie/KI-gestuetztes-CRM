from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import Consent, DataSubjectRequest


@admin.register(Consent)
class ConsentAdmin(ModelAdmin):
    list_display = ["person", "purpose", "company", "granted_at", "revoked_at"]
    list_filter = ["purpose"]
    autocomplete_fields = ["person", "company"]


@admin.register(DataSubjectRequest)
class DataSubjectRequestAdmin(ModelAdmin):
    list_display = ["requester_name", "kind", "received_at", "due_date", "completed_at"]
    list_filter = ["kind"]
