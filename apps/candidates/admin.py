from django.contrib import admin

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


@admin.register(DuplicateSuggestion)
class DuplicateSuggestionAdmin(admin.ModelAdmin):
    list_display = ["person_a", "person_b", "reason", "status"]
    list_filter = ["status"]
