from agents.base import BaseAgent
from agents.registry import register


@register
class CVReparseAgent(BaseAgent):
    """Liest den aktuellen Lebenslauf eines Kandidatenprofils neu aus und aktualisiert das Profil."""
    name = "cv_reparse"

    def run(self, profile_id: int) -> dict:
        from apps.candidates.models import CandidateProfile
        from apps.candidates.services import reparse_profile

        r = reparse_profile(CandidateProfile.objects.select_related("person").get(pk=profile_id))
        return {"profile_id": profile_id, "status": r.status, "message": r.message}
