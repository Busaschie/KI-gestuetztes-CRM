import os

# Tests laufen ohne .env-Pflichtwerte
os.environ.setdefault("DJANGO_SECRET_KEY", "test")
os.environ.setdefault("DATABASE_URL", "postgres://sandra:sandra@localhost:5432/sandra_crm")


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _contractor_defaults(settings):
    """Vertrags-PDF braucht Daten der Auftragnehmerin – in Tests feste Werte statt .env."""
    settings.CONTRACTOR_NAME = settings.CONTRACTOR_NAME or "Test Auftragnehmerin"
    settings.CONTRACTOR_SIGNER = settings.CONTRACTOR_SIGNER or "Test Signerin"
