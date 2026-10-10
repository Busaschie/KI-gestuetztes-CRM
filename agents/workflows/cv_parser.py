from agents.base import BaseAgent
from agents.registry import register


@register
class CVParserAgent(BaseAgent):
    """Liest einen eingegangenen Lebenslauf aus und ordnet ihn einer Person zu."""
    name = "cv_parser"

    def run(self, inbound_id: int, origin: str = "import") -> dict:
        from apps.candidates.services import process_cv_inbound
        from apps.communications.models import InboundItem

        item = InboundItem.objects.get(pk=inbound_id)
        result = process_cv_inbound(item, origin=origin)
        return {
            "inbound_id": inbound_id,
            "status": result.status,
            "person_id": result.person.pk if result.person else None,
            "message": result.message,
        }
