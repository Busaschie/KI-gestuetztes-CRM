"""Aufträge (Mandate) von Kunden."""
from django.db import models

from apps.contacts.models import Company, Person
from apps.core.models import Origin, TimeStampedModel


class Mandate(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Entwurf"
        ACTIVE = "active", "Aktiv"
        ON_HOLD = "on_hold", "Pausiert"
        FILLED = "filled", "Besetzt"
        CANCELLED = "cancelled", "Abgebrochen"

    company = models.ForeignKey(Company, on_delete=models.PROTECT, related_name="mandates", verbose_name="Kunde")
    contact_person = models.ForeignKey(
        Person, on_delete=models.SET_NULL, null=True, blank=True, related_name="mandates", verbose_name="Ansprechpartner"
    )
    title = models.CharField("Position", max_length=255)
    location = models.CharField("Einsatzort", max_length=255, blank=True)
    salary_budget = models.PositiveIntegerField("Gehaltsbudget (brutto/Jahr)", null=True, blank=True)
    description = models.TextField("Stellenbeschreibung", blank=True)
    must_have = models.JSONField("Musskriterien", default=list, blank=True)
    nice_to_have = models.JSONField("Wunschkriterien", default=list, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    origin = models.CharField(
        "Herkunft des Auftrags", max_length=20, choices=Origin.choices, blank=True,
        help_text="Herkunftsnachweis: welche Kontaktpflege bringt Aufträge (P2 Punkt 8)",
    )
    origin_person = models.ForeignKey(
        Person, on_delete=models.SET_NULL, null=True, blank=True, related_name="referred_mandates",
        verbose_name="Auftrag kam über",
    )

    class Meta:
        verbose_name = "Auftrag"
        verbose_name_plural = "Aufträge"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} – {self.company}"

    @property
    def has_signed_contract(self) -> bool:
        """Harte Sperre (P1 Punkt 4): ohne unterschriebenen Vertrag kein Profilversand über das System."""
        from apps.clients.models import Contract
        return self.contracts.filter(status__in=Contract.SIGNED_STATES).exists()
