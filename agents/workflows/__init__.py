"""Lädt alle Agenten-Module in diesem Ordner, damit sich ihre @register-Klassen anmelden."""
import importlib
import pkgutil

for _mod in pkgutil.iter_modules(__path__):
    importlib.import_module(f"{__name__}.{_mod.name}")
