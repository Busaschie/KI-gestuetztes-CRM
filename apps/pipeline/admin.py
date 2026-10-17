from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import Submission


@admin.register(Submission)
class SubmissionAdmin(ModelAdmin):
    list_display = ["candidate", "mandate", "stage", "spoken_with", "consent_to_present_at", "last_feedback_at"]
    list_filter = ["stage", "spoken_with"]
    autocomplete_fields = ["candidate", "mandate"]
