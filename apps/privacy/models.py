"""Einwilligungen und Betroffenenanfragen (DSGVO, siehe work/datenschutz.md)."""
from django.db import models

from apps.contacts.models import Company, Person
from apps.core.models import TimeStampedModel


class Consent(TimeStampedModel):
    class Purpose(models.TextChoices):
        STORAGE = "storage", "Speicherung im Kandidatenpool"
        PRESENT_TO_CLIENT = "present", "Vorstellung bei einem Kunden"
        CONTACT = "contact", "Kontaktaufnahme / Newsletter"

    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="consents")
    purpose = models.CharField("Zweck", max_length=10, choices=Purpose.choices)
    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, null=True, blank=True, help_text="Nur bei Vorstellung beim Kunden"
    )
    granted_at = models.DateTimeField("Erteilt am")
    revoked_at = models.DateTimeField("Widerrufen am", null=True, blank=True)
    evidence = models.TextField("Nachweis", help_text="z. B. E-Mail vom …, Sprachnotiz-ID")

    class Meta:
        verbose_name = "Einwilligung"
        verbose_name_plural = "Einwilligungen"

    def __str__(self):
        return f"{self.person}: {self.get_purpose_display()}"

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None


class DataSubjectRequest(TimeStampedModel):
    """Auskunft, Berichtigung, Löschung – mit Frist (1 Monat nach Art. 12 DSGVO)."""
    class Kind(models.TextChoices):
        ACCESS = "access", "Auskunft"
        RECTIFICATION = "rectification", "Berichtigung"
        ERASURE = "erasure", "Löschung"
        OBJECTION = "objection", "Widerspruch"

    person = models.ForeignKey(Person, on_delete=models.SET_NULL, null=True, blank=True)
    requester_name = models.CharField("Name des Anfragenden", max_length=255, help_text="Bleibt nach Löschung erhalten")
    kind = models.CharField("Art", max_length=15, choices=Kind.choices)
    received_at = models.DateTimeField("Eingegangen am")
    due_date = models.DateField("Frist")
    completed_at = models.DateTimeField("Erledigt am", null=True, blank=True)
    notes = models.TextField("Vermerk", blank=True)

    class Meta:
        verbose_name = "Betroffenenanfrage"
        verbose_name_plural = "Betroffenenanfragen"
        ordering = ["due_date"]

    def __str__(self):
        return f"{self.get_kind_display()} – {self.requester_name}"
