"""Kandidat ↔ Auftrag: Kandidatenhistorie, Status, Freigabe-Vermerk (P1 Punkt 2)."""
from django.db import models

from apps.candidates.models import CandidateProfile
from apps.core.models import TimeStampedModel
from apps.jobs.models import Mandate


class Submission(TimeStampedModel):
    class Stage(models.TextChoices):
        NEW = "new", "Neu"
        IN_TALKS = "in_talks", "Im Gespräch"
        PRESENTED = "presented", "Beim Kunden vorgestellt"
        INTERVIEW = "interview", "Interview"
        REJECTION_PREPARED = "rejection_prepared", "Absage vorbereitet"
        REJECTED = "rejected", "Abgesagt"
        ON_HOLD = "on_hold", "Vorgemerkt"
        PLACED = "placed", "Vermittelt"

    class RejectionReason(models.TextChoices):
        """Feste Kategorien – auch für den anonymisierten Suchbericht (P2 Punkt 10)."""
        SALARY = "salary", "Gehalt"
        WILLINGNESS = "willingness", "Wechselbereitschaft"
        SKILL_GAP = "skill_gap", "Fachliche Lücke"
        LOCATION = "location", "Standort/Pendeln"
        CANDIDATE_DECLINED = "candidate_declined", "Kandidat hat abgesagt"
        CLIENT_DECLINED = "client_declined", "Kunde hat abgesagt"

    candidate = models.ForeignKey(CandidateProfile, on_delete=models.CASCADE, related_name="submissions")
    mandate = models.ForeignKey(Mandate, on_delete=models.CASCADE, related_name="submissions")
    stage = models.CharField(max_length=20, choices=Stage.choices, default=Stage.NEW)
    spoken_with = models.BooleanField(
        "Persönlich gesprochen", default=False,
        help_text="Ohne Gespräch: Standardabsage möglich; mit Gespräch: persönliche Absage",
    )
    consent_to_present_at = models.DateTimeField(
        "Zustimmung zur Vorstellung beim Kunden", null=True, blank=True,
        help_text="Profil mit Namen nur nach dokumentierter Zustimmung des Kandidaten",
    )
    presented_at = models.DateTimeField("Beim Kunden vorgestellt am", null=True, blank=True)
    rejection_reason = models.CharField("Absagegrund", max_length=20, choices=RejectionReason.choices, blank=True)
    last_feedback_at = models.DateTimeField(
        "Letzte Rückmeldung an Kandidat", null=True, blank=True, help_text="Regel: nie länger als 14 Tage ohne Rückmeldung"
    )

    class Meta:
        verbose_name = "Kandidat im Auftrag"
        verbose_name_plural = "Kandidaten in Aufträgen"
        constraints = [models.UniqueConstraint(fields=["candidate", "mandate"], name="uniq_candidate_mandate")]
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.candidate} → {self.mandate} ({self.get_stage_display()})"

    @property
    def can_be_sent_to_client(self) -> bool:
        return bool(self.consent_to_present_at) and self.mandate.has_signed_contract
