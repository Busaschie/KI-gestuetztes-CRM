"""Personen und Unternehmen – die gemeinsame Basis aller Bereiche (Grundsatz 1).

Eine Person kann gleichzeitig Kandidat, Ansprechpartner beim Kunden und LinkedIn-Kontakt sein.
Geschützte Merkmale (Alter, Geschlecht, Herkunft, Religion, Behinderung, Familie) werden
bewusst NICHT als Felder geführt.
"""
from django.db import models

from apps.core.models import Origin, TimeStampedModel


class Company(TimeStampedModel):
    name = models.CharField("Name", max_length=255)
    legal_form = models.CharField("Rechtsform", max_length=50, blank=True)
    street = models.CharField("Straße", max_length=255, blank=True)
    postal_code = models.CharField("PLZ", max_length=20, blank=True)
    city = models.CharField("Ort", max_length=100, blank=True)
    country = models.CharField("Land", max_length=2, blank=True, help_text="ISO-Code, z. B. AT")
    vat_id = models.CharField("USt-IdNr.", max_length=30, blank=True)
    website = models.URLField("Website", blank=True)
    industry = models.CharField("Branche", max_length=100, blank=True)
    is_client = models.BooleanField("Ist Kunde", default=False)
    signatory = models.ForeignKey(
        "Person", verbose_name="Unterzeichner", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="signatory_for",
    )
    notes = models.TextField("Notizen", blank=True)

    class Meta:
        verbose_name = "Unternehmen"
        verbose_name_plural = "Unternehmen"
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def has_contract_master_data(self) -> bool:
        """Vertragsstammdaten vollständig? Voraussetzung für automatischen Vertragsversand."""
        return all([self.legal_form, self.street, self.postal_code, self.city, self.country, self.signatory_id])


class Person(TimeStampedModel):
    first_name = models.CharField("Vorname", max_length=100, blank=True)
    last_name = models.CharField("Nachname", max_length=100)
    email = models.EmailField("E-Mail", blank=True, db_index=True)
    phone = models.CharField("Telefon", max_length=50, blank=True)
    linkedin_url = models.URLField("LinkedIn-Profil", blank=True, db_index=True)
    city = models.CharField("Wohnort", max_length=100, blank=True)
    region = models.CharField("Region", max_length=100, blank=True)
    country = models.CharField("Land", max_length=2, blank=True)
    preferred_language = models.CharField(
        "Korrespondenzsprache", max_length=5, blank=True, help_text="Für Informationspflicht und Absagen, z. B. de, ro"
    )
    last_contacted_at = models.DateTimeField("Letzter Kontakt", null=True, blank=True,
                                             help_text="Automatisch: Notiz, gesendete Nachricht, Kontaktpflege erledigt")
    no_contact_care = models.BooleanField("Keine Kontaktpflege", default=False,
                                          help_text="Keine automatischen Kontaktvorschläge für diese Person")
    retain_until = models.DateField(
        "Speichern bis", null=True, blank=True, help_text="Löschfrist – danach Löschung vorschlagen"
    )

    class Meta:
        verbose_name = "Person"
        verbose_name_plural = "Personen"
        ordering = ["last_name", "first_name"]

    def __str__(self):
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def current_employment(self):
        return self.employments.filter(is_current=True).select_related("company").first()


class Employment(TimeStampedModel):
    """Wer arbeitet wo – auch Historie, Grundlage für Jobwechsel-Erkennung (P1 Punkt 3)."""
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="employments")
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="employments")
    title = models.CharField("Position", max_length=255, blank=True)
    start_date = models.DateField("Von", null=True, blank=True)
    end_date = models.DateField("Bis", null=True, blank=True)
    is_current = models.BooleanField("Aktuell", default=True)
    origin = models.CharField("Quelle", max_length=20, choices=Origin.choices, default=Origin.MANUAL)

    class Meta:
        verbose_name = "Beschäftigung"
        verbose_name_plural = "Beschäftigungen"
        ordering = ["-is_current", "-start_date"]

    def __str__(self):
        return f"{self.person} – {self.title} @ {self.company}"


class PersonOrigin(TimeStampedModel):
    """Herkunftsvermerk – eine Person kann mehrere Herkünfte haben."""
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="origins")
    origin = models.CharField("Herkunft", max_length=20, choices=Origin.choices)
    detail = models.CharField("Detail", max_length=255, blank=True, help_text="z. B. Name der Jobbörse, Empfehlungsgeber")

    class Meta:
        verbose_name = "Herkunft"
        verbose_name_plural = "Herkünfte"
        constraints = [models.UniqueConstraint(fields=["person", "origin", "detail"], name="uniq_person_origin")]

    def __str__(self):
        return self.get_origin_display()


def client_contact_q() -> models.Q:
    """Ansprechpartner beim Kunden: Ansprechpartner eines Auftrags, Unterzeichner (Firma/Vertrag) oder aktuell bei einem Kunden."""
    return (models.Q(mandates__isnull=False) | models.Q(signatory_for__isnull=False)
            | models.Q(contracts_to_sign__isnull=False)
            | models.Q(employments__is_current=True, employments__company__is_client=True))
