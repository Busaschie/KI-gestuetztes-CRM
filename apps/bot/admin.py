from django.contrib import admin

from .models import BotDraft


@admin.register(BotDraft)
class BotDraftAdmin(admin.ModelAdmin):
    list_display = ["created_at", "status", "person", "inbound"]
    list_filter = ["status"]
    readonly_fields = ["chat_id", "inbound", "data", "candidates", "message_id"]
