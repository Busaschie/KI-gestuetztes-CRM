from django.contrib import admin, messages
from django.utils import timezone
from unfold.admin import ModelAdmin, TabularInline

from .models import FollowUp, InboundItem, Note, OutboundAttachment, OutboundMessage
from .services import MessageError, schedule_message, send_now, stop_message


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


class OutboundAttachmentInline(TabularInline):
    model = OutboundAttachment
    extra = 0
    fields = ["cv", "filename"]
    readonly_fields = ["cv"]
    verbose_name_plural = "Anhänge (Original-CV)"


@admin.register(OutboundMessage)
class OutboundMessageAdmin(ModelAdmin):
    list_display = ["created_at", "kind", "recipient", "subject", "status", "scheduled_for", "sent_at"]
    list_filter = ["kind", "status", "is_automatic"]
    search_fields = ["subject", "recipient__last_name", "mandate__title"]
    autocomplete_fields = ["recipient", "mandate", "submissions"]
    readonly_fields = ["status", "approved_at", "scheduled_for", "sent_at", "error"]
    fields = ["kind", "recipient", "mandate", "submissions", "subject", "body",
              "status", "approved_at", "scheduled_for", "sent_at", "error", "is_automatic"]
    inlines = [OutboundAttachmentInline]
    actions = ["action_send", "action_stop", "action_send_now"]

    def _run(self, request, queryset, func, ok):
        for msg in queryset:
            try:
                func(msg)
                self.message_user(request, f"{msg.subject}: {ok(msg)}", messages.SUCCESS)
            except MessageError as e:
                self.message_user(request, f"{msg.subject}: {e}", messages.ERROR)

    @admin.action(description="Freigeben und senden (mit Stopp-Fenster)")
    def action_send(self, request, queryset):
        self._run(request, queryset, schedule_message, lambda m: (
            f"Versand geplant für {timezone.localtime(m.scheduled_for):%H:%M} (Stopp bis dahin möglich)."
            if m.scheduled_for else "versendet."))

    @admin.action(description="Geplanten Versand stoppen")
    def action_stop(self, request, queryset):
        self._run(request, queryset, stop_message, lambda m: "gestoppt.")

    @admin.action(description="Sofort senden (ohne Stopp-Fenster)")
    def action_send_now(self, request, queryset):
        self._run(request, queryset, send_now, lambda m: "versendet.")
