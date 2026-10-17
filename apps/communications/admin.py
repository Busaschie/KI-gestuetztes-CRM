from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import FollowUp, InboundItem, Note, OutboundMessage


@admin.register(Note)
class NoteAdmin(ModelAdmin):
    list_display = ["person", "origin", "created_at"]
    search_fields = ["text", "person__last_name"]
    autocomplete_fields = ["person", "mandate"]


@admin.register(FollowUp)
class FollowUpAdmin(ModelAdmin):
    list_display = ["due_date", "text", "person", "reason", "done_at"]
    list_filter = ["reason"]
    autocomplete_fields = ["person", "mandate"]


@admin.register(InboundItem)
class InboundItemAdmin(ModelAdmin):
    list_display = ["created_at", "channel", "status", "subject", "sender", "person", "error"]
    search_fields = ["subject", "sender", "context", "raw_text"]
    list_filter = ["channel", "status"]
    actions = ["reprocess_cv"]

    @admin.action(description="Lebenslauf erneut verarbeiten")
    def reprocess_cv(self, request, queryset):
        from agents.tasks import enqueue_agent

        for item in queryset.exclude(attachment=""):
            enqueue_agent("cv_parser", inbound_id=item.pk)
        self.message_user(request, f"{queryset.count()} Eingang/Eingänge in die Warteschlange gelegt.")


@admin.register(OutboundMessage)
class OutboundMessageAdmin(ModelAdmin):
    list_display = ["created_at", "kind", "recipient", "status", "is_automatic", "scheduled_for", "sent_at"]
    list_filter = ["kind", "status", "is_automatic"]
    autocomplete_fields = ["recipient", "mandate"]
