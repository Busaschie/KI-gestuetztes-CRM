"""Kundenbeziehung: Honorarmodelle und Verträge (P1 Punkt 4)."""
from django.db import models

from apps.contacts.models import Company
from apps.core.models import TimeStampedModel
from apps.jobs.models import Mandate


class FeeModel(TimeStampedModel):
    name = models.CharField("Bezeichnung", max_length=100, help_text="z. B. Einzelauftrag 20 %")
    percent = models.DecimalField("Honorar in % vom Jahresgehalt", max_digits=5, decimal_places=2)
    guarantee_terms = models.TextField("Garantiebedingungen", blank=True)
    is_default = models.BooleanField("Standard", default=False)

    class Meta:
        verbose_name = "Honorarmodell"
        verbose_name_plural = "Honorarmodelle"

    def __str__(self):
        return self.name


class Contract(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Entwurf"
        SENT = "sent", "Versendet"
        PENDING = "pending", "Unterschrift ausständig"
        SIGNED = "signed", "Unterschrieben"
        INVOICE_DUE = "invoice_due", "Rechnung fällig"
        PAID = "paid", "Bezahlt"
        CANCELLED = "cancelled", "Storniert"

    SIGNED_STATES = (Status.SIGNED, Status.INVOICE_DUE, Status.PAID)

    mandate = models.ForeignKey(Mandate, on_delete=models.PROTECT, related_name="contracts", verbose_name="Auftrag")
    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name="contracts", verbose_name="Kunde")
    fee_model = models.ForeignKey(FeeModel, on_delete=models.PROTECT, verbose_name="Honorarmodell")
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.DRAFT)
    deviations = models.TextField(
        "Abweichungen von der Vorlage", blank=True, help_text="Nur bei Abweichungen ist eine Freigabe nötig"
    )
    signature_provider_id = models.CharField("ID beim E-Signatur-Dienst", max_length=255, blank=True)
    sent_at = models.DateTimeField("Versendet am", null=True, blank=True)
    signed_at = models.DateTimeField("Unterschrieben am", null=True, blank=True)
    reminders_sent = models.PositiveSmallIntegerField("Erinnerungen gesendet", default=0)
    document = models.FileField("Vertragsdokument", upload_to="contracts/", blank=True)

    class Meta:
        verbose_name = "Vertrag"
        verbose_name_plural = "Verträge"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Vertrag {self.mandate} ({self.get_status_display()})"

    @property
    def needs_approval(self) -> bool:
        return bool(self.deviations.strip())
