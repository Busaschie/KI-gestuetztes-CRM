from django.contrib import admin

from .display import render_profile
from .models import CandidateProfile, CVDocument, DuplicateSuggestion


class CVInline(admin.TabularInline):
    model = CVDocument
    extra = 0
    fields = ["file", "original_filename", "received_at", "origin", "is_current"]


@admin.register(CandidateProfile)
class CandidateProfileAdmin(admin.ModelAdmin):
    list_display = ["person", "headline", "years_experience", "available_from", "on_hold_until"]
    search_fields = ["person__first_name", "person__last_name", "headline"]
    autocomplete_fields = ["person"]
    inlines = [CVInline]
    readonly_fields = ["overview"]
    fieldsets = [
        (None, {"fields": ["person", "headline", "summary"]}),
        ("Eckdaten", {"fields": [
            ("years_experience", "has_leadership"),
            ("available_from", "on_hold_until"),
            ("salary_expectation", "willing_to_relocate"),
        ]}),
        ("Profil aus dem Lebenslauf", {"fields": ["overview"]}),
        ("Rohdaten (JSON, zum Bearbeiten)", {"classes": ["collapse"], "fields": [
            "positions", "education", "certifications", "other_experience",
            "industries", "skills", "strengths", "interests", "languages",
        ]}),
    ]

    @admin.display(description="Übersicht")
    def overview(self, obj):
        if not obj or not obj.pk:
            return "Wird nach dem Speichern bzw. nach der CV-Auslese angezeigt."
        return render_profile(obj)


@admin.register(DuplicateSuggestion)
class DuplicateSuggestionAdmin(admin.ModelAdmin):
    list_display = ["person_a", "person_b", "reason", "status"]
    list_filter = ["status"]
