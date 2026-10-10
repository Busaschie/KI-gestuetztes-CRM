from abc import ABC, abstractmethod


class BaseAgent(ABC):
    """Gemeinsame Schnittstelle aller Agenten."""
    name: str = "base"

    @abstractmethod
    def run(self, **kwargs) -> dict:
        ...
