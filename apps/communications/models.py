"""Notizen, Wiedervorlagen, Eingänge und ausgehende Nachrichten."""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.contacts.models import Person
from apps.core.models import Origin, TimeStampedModel
from apps.jobs.models import Mandate


class Note(TimeStampedModel):
    """Gesprächsnotiz – z. B. aus einer Sprachnachricht."""
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="notes")
    mandate = models.ForeignKey(Mandate, on_delete=models.SET_NULL, null=True, blank=True, related_name="notes")
    text = models.TextField("Notiz")
    origin = models.CharField("Quelle", max_length=20, choices=Origin.choices, default=Origin.MANUAL)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        verbose_name = "Notiz"
        verbose_name_plural = "Notizen"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.person}: {self.text[:50]}"


class FollowUp(TimeStampedModel):
    """Wiedervorlage – aus Sprachnotiz oder fester Regel (P1 Punkt 6)."""
    class Reason(models.TextChoices):
        NOTE = "note", "Aus Notiz"
        RULE_6_MONTHS = "rule_6m", "Kontaktpflege 6 Monate"
        JOB_CHANGE = "job_change", "Jobwechsel"
        ON_HOLD = "on_hold", "Vorgemerkter Kandidat"
        CONTRACT = "contract", "Vertrag nicht unterschrieben"
        OTHER = "other", "Sonstiges"

    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="follow_ups", null=True, blank=True)
    mandate = models.ForeignKey(Mandate, on_delete=models.CASCADE, related_name="follow_ups", null=True, blank=True)
    due_date = models.DateField("Fällig am", db_index=True)
    reason = models.CharField("Anlass", max_length=15, choices=Reason.choices, default=Reason.OTHER)
    text = models.CharField("Was ist zu tun", max_length=255)
    source_note = models.ForeignKey(Note, on_delete=models.SET_NULL, null=True, blank=True)
    done_at = models.DateTimeField("Erledigt am", null=True, blank=True)

    class Meta:
        verbose_name = "Wiedervorlage"
        verbose_name_plural = "Wiedervorlagen"
        ordering = ["due_date"]

    def __str__(self):
        return f"{self.due_date:%d.%m.%Y}: {self.text}"


class InboundItem(TimeStampedModel):
    """Jeder Eingang (E-Mail, Sprachnachricht, Import) – mit Zuordnungsstatus (Grundsatz 8)."""
    class Channel(models.TextChoices):
        EMAIL = "email", "E-Mail"
        VOICE = "voice", "Sprachnachricht"
        TELEGRAM = "telegram", "Telegram-Text"
        LINKEDIN_CSV = "linkedin_csv", "LinkedIn-Export"
        FILE_IMPORT = "file_import", "Datei-Import"

    class Status(models.TextChoices):
        RECEIVED = "received", "Eingegangen"
        ASSIGNED = "assigned", "Zugeordnet"
        UNASSIGNED = "unassigned", "Nicht zugeordnet"
        NEEDS_QUESTION = "needs_question", "Rückfrage nötig"
        FAILED = "failed", "Fehler"
        IGNORED = "ignored", "Ignoriert"

    channel = models.CharField(max_length=15, choices=Channel.choices)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.RECEIVED, db_index=True)
    external_id = models.CharField("Externe ID", max_length=255, blank=True, db_index=True, help_text="z. B. Message-ID")
    subject = models.CharField("Betreff / Dateiname", max_length=255, blank=True)
    sender = models.CharField("Absender", max_length=255, blank=True)
    context = models.CharField("Kontext", max_length=255, blank=True, help_text="z. B. Betreff der E-Mail mit dem Anhang")
    raw_text = models.TextField("Inhalt / Transkript", blank=True)
    attachment = models.FileField("Anhang (Original)", upload_to="inbound/%Y/%m/", blank=True)
    person = models.ForeignKey(Person, on_delete=models.SET_NULL, null=True, blank=True, related_name="inbound_items")
    error = models.TextField("Ergebnis / Fehler", blank=True)
    processed_at = models.DateTimeField("Verarbeitet am", null=True, blank=True)

    class Meta:
        verbose_name = "Eingang"
        verbose_name_plural = "Eingänge"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_channel_display()}: {self.subject or self.raw_text[:40]}"


class OutboundMessage(TimeStampedModel):
    """Alles, was nach außen geht – mit Freigabe, Stopp-Zeitfenster und Protokoll (Grundsatz 3)."""
    class Kind(models.TextChoices):
        STANDARD_REJECTION = "std_rejection", "Standardabsage"
        PERSONAL_REJECTION = "pers_rejection", "Persönliche Absage"
        CONTRACT = "contract", "Vertrag"
        CONTRACT_REMINDER = "contract_reminder", "Vertragserinnerung"
        PROFILE_TO_CLIENT = "profile", "Profil an Kunden"
        OUTREACH = "outreach", "Ansprache"
        OTHER = "other", "Sonstiges"

    class Status(models.TextChoices):
        DRAFT = "draft", "Entwurf"
        AWAITING_APPROVAL = "awaiting", "Wartet auf Freigabe"
        SCHEDULED = "scheduled", "Geplant (Stopp möglich)"
        STOPPED = "stopped", "Gestoppt"
        SENT = "sent", "Gesendet"
        FAILED = "failed", "Fehler"

    kind = models.CharField(max_length=20, choices=Kind.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT, db_index=True)
    recipient = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="outbound_messages")
    mandate = models.ForeignKey(Mandate, on_delete=models.SET_NULL, null=True, blank=True)
    subject = models.CharField("Betreff", max_length=255)
    body = models.TextField("Text")
    is_automatic = models.BooleanField("Automatischer Versand", default=False)
    scheduled_for = models.DateTimeField("Geplant für", null=True, blank=True, help_text="Bis dahin kann gestoppt werden")
    approved_at = models.DateTimeField("Freigegeben am", null=True, blank=True)
    sent_at = models.DateTimeField("Gesendet am", null=True, blank=True)
    error = models.TextField("Fehler", blank=True)

    class Meta:
        verbose_name = "Ausgehende Nachricht"
        verbose_name_plural = "Ausgehende Nachrichten"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_kind_display()} an {self.recipient} ({self.get_status_display()})"

    # Status, in denen eine Nachricht unterwegs ist oder war – hier greift die Vertragssperre
    ACTIVE_STATES = (Status.AWAITING_APPROVAL, Status.SCHEDULED, Status.SENT)

    def check_contract_lock(self):
        """Harte Sperre (P1 Punkt 4): Profil an Kunden nur bei unterschriebenem Vertrag zum Auftrag.
        Entwürfe sind erlaubt, damit Sandra vorbereiten kann."""
        if self.kind != self.Kind.PROFILE_TO_CLIENT or self.status not in self.ACTIVE_STATES:
            return
        if not self.mandate_id:
            raise ValidationError({"mandate": "Profilversand an Kunden nur mit zugeordnetem Auftrag."})
        if not self.mandate.has_signed_contract:
            raise ValidationError("Gesperrt: Für diesen Auftrag gibt es keinen unterschriebenen Vertrag.")

    def clean(self):
        super().clean()
        self.check_contract_lock()

    def save(self, *args, **kwargs):
        self.check_contract_lock()  # auch außerhalb des Admins (Agenten, Telegram, Skripte)
        super().save(*args, **kwargs)
