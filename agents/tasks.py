from celery import shared_task

from . import workflows  # noqa: F401  – registriert alle Agenten
from .registry import get_agent


@shared_task
def run_agent(name: str, **kwargs) -> dict:
    """Startet einen Agenten asynchron über Celery."""
    return get_agent(name).run(**kwargs)
