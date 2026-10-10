"""Zentrale Registrierung: neue Agenten per @register hinzufügen."""
from .base import BaseAgent

_REGISTRY: dict[str, type[BaseAgent]] = {}


def register(cls: type[BaseAgent]) -> type[BaseAgent]:
    _REGISTRY[cls.name] = cls
    return cls


def get_agent(name: str) -> BaseAgent:
    return _REGISTRY[name]()
