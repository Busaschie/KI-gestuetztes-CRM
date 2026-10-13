from django.db import models

from apps.communications.models import InboundItem
from apps.contacts.models import Person
from apps.core.models import TimeStampedModel


class BotDraft(TimeStampedModel):
    """Vorschlag aus einer Telegram-Nachricht – wird erst nach Bestätigung zu Notiz/Wiedervorlage."""
    class Status(models.TextChoices):
        PROCESSING = "processing", "In Verarbeitung"
        AWAITING = "awaiting", "Wartet auf Bestätigung"
        SAVED = "saved", "Gespeichert"
        CANCELLED = "cancelled", "Verworfen"
        FAILED = "failed", "Fehler"

    chat_id = models.BigIntegerField()
    inbound = models.OneToOneField(InboundItem, on_delete=models.CASCADE, related_name="bot_draft")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PROCESSING, db_index=True)
    data = models.JSONField("Erkannt", default=dict, blank=True)
    candidates = models.JSONField("Mögliche Personen (IDs)", default=list, blank=True)
    person = models.ForeignKey(Person, on_delete=models.SET_NULL, null=True, blank=True)
    message_id = models.BigIntegerField("Telegram-Nachricht mit Knöpfen", null=True, blank=True)

    class Meta:
        verbose_name = "Telegram-Vorschlag"
        verbose_name_plural = "Telegram-Vorschläge"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Vorschlag #{self.pk} ({self.get_status_display()})"
