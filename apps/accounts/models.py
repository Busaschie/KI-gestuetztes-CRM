from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    """Eigenes User-Modell von Anfang an – spätere Erweiterung ohne Migrationsprobleme."""
