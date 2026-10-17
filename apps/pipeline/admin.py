from django.contrib import admin, messages
from django.shortcuts import redirect
from django.urls import reverse
from unfold.admin import ModelAdmin

from apps.communications.services import MessageError, prepare_profile_message

from .models import Submission


@admin.register(Submission)
class SubmissionAdmin(ModelAdmin):
    list_filter = ["stage", "spoken_with"]
    list_display = ["candidate", "mandate", "stage", "spoken_with", "consent_to_present_at", "presented_at",
                    "last_feedback_at"]
    autocomplete_fields = ["candidate", "mandate"]
    search_fields = ["candidate__person__first_name", "candidate__person__last_name", "mandate__title"]
    actions = ["action_prepare_profile"]

    @admin.action(description="Profil an Kunden vorbereiten (Entwurf mit CV)")
    def action_prepare_profile(self, request, queryset):
        try:
            msg = prepare_profile_message(queryset.select_related("candidate__person", "mandate__contact_person"))
        except MessageError as e:
            self.message_user(request, str(e), messages.ERROR)
            return None
        self.message_user(request, "Entwurf angelegt – Text prüfen, dann „Freigeben und senden“.", messages.SUCCESS)
        return redirect(reverse("admin:communications_outboundmessage_change", args=[msg.pk]))
