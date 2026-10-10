from django.db import models


class TimeStampedModel(models.Model):
    """Basis für alle Modelle: Erstellt/Geändert-Zeitstempel."""
    created_at = models.DateTimeField("Erstellt", auto_now_add=True)
    updated_at = models.DateTimeField("Geändert", auto_now=True)

    class Meta:
        abstract = True


class Origin(models.TextChoices):
    """Woher ein Datensatz/Eingang stammt (Herkunftsvermerk, P1 Punkt 3)."""
    LINKEDIN = "linkedin", "LinkedIn"
    PERSONAL = "personal", "Persönlich"
    APPLICATION = "application", "Bewerbung"
    REFERRAL = "referral", "Empfehlung"
    EMAIL = "email", "E-Mail"
    PLACEMENT = "placement", "Frühere Vermittlung"
    JOB_BOARD = "job_board", "Jobbörse"
    VOICE = "voice", "Sprachnachricht"
    IMPORT = "import", "Import (CV-Ordner/CRM)"
    MANUAL = "manual", "Manuell"
