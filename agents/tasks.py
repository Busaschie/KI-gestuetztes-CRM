from django_q.tasks import async_task

from . import workflows  # noqa: F401  – registriert alle Agenten
from .registry import get_agent


def run_agent(name: str, **kwargs) -> dict:
    """Führt einen Agenten aus (läuft im Hintergrundprozess)."""
    return get_agent(name).run(**kwargs)


def enqueue_agent(name: str, **kwargs) -> str:
    """Legt einen Agenten-Auftrag in die Warteschlange und gibt die Task-ID zurück."""
    return async_task("agents.tasks.run_agent", name, **kwargs)
