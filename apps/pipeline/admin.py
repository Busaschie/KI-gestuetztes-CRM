from django.contrib import admin

from .models import Submission


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = ["candidate", "mandate", "stage", "spoken_with", "consent_to_present_at", "last_feedback_at"]
    list_filter = ["stage", "spoken_with"]
    autocomplete_fields = ["candidate", "mandate"]
