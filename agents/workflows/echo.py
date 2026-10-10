import time

from agents.base import BaseAgent
from agents.registry import register


@register
class EchoAgent(BaseAgent):
    """Test-Agent: prüft den Weg Django → Redis → Celery, ohne LLM-Aufruf."""
    name = "echo"

    def run(self, text: str = "Hallo", delay: int = 2) -> dict:
        time.sleep(delay)  # simuliert eine langsame Aufgabe
        return {"agent": self.name, "echo": text.upper()}
