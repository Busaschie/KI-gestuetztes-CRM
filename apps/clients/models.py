"""Kundenbeziehung: Honorarmodelle und Verträge (P1 Punkt 4)."""
from django.db import models

from apps.contacts.models import Company, Person
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
        SCHEDULED = "scheduled", "Geplant (Stopp möglich)"
        SENT = "sent", "Versendet"
        PENDING = "pending", "Unterschrift ausständig"
        SIGNED = "signed", "Unterschrieben"
        INVOICE_DUE = "invoice_due", "Rechnung fällig"
        PAID = "paid", "Bezahlt"
        DECLINED = "declined", "Abgelehnt"
        EXPIRED = "expired", "Abgelaufen"
        CANCELLED = "cancelled", "Storniert"

    SIGNED_STATES = (Status.SIGNED, Status.INVOICE_DUE, Status.PAID)

    mandate = models.ForeignKey(Mandate, on_delete=models.PROTECT, related_name="contracts", verbose_name="Auftrag")
    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name="contracts", verbose_name="Kunde")
    fee_model = models.ForeignKey(FeeModel, on_delete=models.PROTECT, verbose_name="Honorarmodell")
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.DRAFT)
    deviations = models.TextField(
        "Abweichungen von der Vorlage", blank=True, help_text="Nur bei Abweichungen ist eine Freigabe nötig"
    )
    signer = models.ForeignKey(
        Person, on_delete=models.PROTECT, null=True, blank=True, related_name="contracts_to_sign",
        verbose_name="Unterzeichner", help_text="Leer = Ansprechpartner des Auftrags",
    )
    approved_at = models.DateTimeField("Abweichungen freigegeben am", null=True, blank=True)
    scheduled_for = models.DateTimeField("Versand geplant für", null=True, blank=True,
                                         help_text="Bis dahin kann der Versand gestoppt werden")
    signature_provider_id = models.CharField("ID beim E-Signatur-Dienst", max_length=255, blank=True, db_index=True)
    signature_submitter_id = models.CharField("ID des Unterzeichners beim Dienst", max_length=255, blank=True)
    signing_url = models.URLField("Link zur Unterschrift", max_length=500, blank=True)
    declined_at = models.DateTimeField("Abgelehnt am", null=True, blank=True)
    decline_reason = models.TextField("Ablehnungsgrund", blank=True)
    sent_at = models.DateTimeField("Versendet am", null=True, blank=True)
    signed_at = models.DateTimeField("Unterschrieben am", null=True, blank=True)
    reminders_sent = models.PositiveSmallIntegerField("Erinnerungen gesendet", default=0)
    last_reminder_at = models.DateTimeField("Letzte Erinnerung", null=True, blank=True)
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

    @property
    def is_signed(self) -> bool:
        return self.status in self.SIGNED_STATES

    def get_signer(self):
        return self.signer or self.mandate.contact_person


class ContractEvent(models.Model):
    """Protokoll: Versand, Webhooks des Signaturdiensts, Fehler – wird nie verändert."""
    contract = models.ForeignKey(Contract, on_delete=models.CASCADE, related_name="events")
    created_at = models.DateTimeField("Zeitpunkt", auto_now_add=True)
    kind = models.CharField("Ereignis", max_length=50)
    message = models.TextField("Beschreibung", blank=True)
    payload = models.JSONField("Rohdaten", default=dict, blank=True)

    class Meta:
        verbose_name = "Vertragsereignis"
        verbose_name_plural = "Vertragsereignisse"
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.created_at:%d.%m.%Y %H:%M} {self.kind}"
