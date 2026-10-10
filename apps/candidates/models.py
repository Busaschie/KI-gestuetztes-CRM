"""Kandidatenprofil und CV-Versionen (P1 Punkt 2). Personendaten liegen in contacts.Person."""
import hashlib

from django.db import models

from apps.contacts.models import Person
from apps.core.models import Origin, TimeStampedModel


class CandidateProfile(TimeStampedModel):
    person = models.OneToOneField(Person, on_delete=models.CASCADE, related_name="candidate_profile")
    headline = models.CharField("Kurzprofil", max_length=255, blank=True, help_text="z. B. Vertriebsleiter Maschinenbau")
    summary = models.TextField("Zusammenfassung", blank=True)
    # Strukturierte Profildaten aus dem CV (KI-Auslese). Listen als JSON, z. B. [{"name": "Englisch", "level": "C1"}]
    positions = models.JSONField("Positionen", default=list, blank=True)
    education = models.JSONField("Aus- und Weiterbildung", default=list, blank=True)
    certifications = models.JSONField("Zertifikate", default=list, blank=True)
    other_experience = models.JSONField("Sonstiges (z. B. Wehrdienst, Ehrenamt)", default=list, blank=True)
    industries = models.JSONField("Branchen", default=list, blank=True)
    skills = models.JSONField("Kompetenzen", default=list, blank=True)
    strengths = models.JSONField("Persönliche Stärken", default=list, blank=True)
    interests = models.JSONField("Interessen und Leistungen", default=list, blank=True)
    languages = models.JSONField("Sprachen", default=list, blank=True)
    years_experience = models.PositiveSmallIntegerField("Berufserfahrung (Jahre)", null=True, blank=True)
    has_leadership = models.BooleanField("Führungserfahrung", null=True, blank=True)
    available_from = models.DateField("Verfügbar ab", null=True, blank=True)
    salary_expectation = models.PositiveIntegerField("Gehaltswunsch (brutto/Jahr)", null=True, blank=True)
    willing_to_relocate = models.BooleanField("Umzugsbereit", null=True, blank=True)
    on_hold_until = models.DateField("Vorgemerkt bis", null=True, blank=True, help_text="Wiedervorlage nach Absage")
    # Suchindex (pgvector) folgt, sobald das Embedding-Modell feststeht.

    class Meta:
        verbose_name = "Kandidatenprofil"
        verbose_name_plural = "Kandidatenprofile"

    def __str__(self):
        return str(self.person)


def cv_upload_path(instance, filename):
    return f"cvs/{instance.profile.person_id}/{filename}"


class CVDocument(TimeStampedModel):
    """Eine CV-Version. Originale werden nie verändert, ältere Versionen bleiben abrufbar."""
    profile = models.ForeignKey(CandidateProfile, on_delete=models.CASCADE, related_name="cvs")
    file = models.FileField("Datei", upload_to=cv_upload_path)
    original_filename = models.CharField("Originaler Dateiname", max_length=255)
    checksum = models.CharField("SHA-256", max_length=64, db_index=True, editable=False)
    received_at = models.DateTimeField("Eingegangen")
    origin = models.CharField("Quelle", max_length=20, choices=Origin.choices)
    is_current = models.BooleanField("Aktuelle Version", default=True)
    extracted_text = models.TextField("Ausgelesener Text", blank=True)
    ocr_used = models.BooleanField("Texterkennung (OCR)", default=False)

    class Meta:
        verbose_name = "Lebenslauf"
        verbose_name_plural = "Lebensläufe"
        ordering = ["-received_at"]

    def __str__(self):
        return f"{self.original_filename} ({self.received_at:%d.%m.%Y})"

    def save(self, *args, **kwargs):
        if not self.checksum and self.file:
            h = hashlib.sha256()
            for chunk in self.file.chunks():
                h.update(chunk)
            self.checksum = h.hexdigest()
        super().save(*args, **kwargs)
        if self.is_current:
            CVDocument.objects.filter(profile=self.profile).exclude(pk=self.pk).update(is_current=False)


class DuplicateSuggestion(TimeStampedModel):
    """Dubletten werden vorgeschlagen, nie automatisch zusammengeführt."""
    class Status(models.TextChoices):
        OPEN = "open", "Offen"
        MERGED = "merged", "Zusammengeführt"
        DISMISSED = "dismissed", "Keine Dublette"

    person_a = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="+")
    person_b = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="+")
    reason = models.CharField("Grund", max_length=255)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)

    class Meta:
        verbose_name = "Dubletten-Vorschlag"
        verbose_name_plural = "Dubletten-Vorschläge"
