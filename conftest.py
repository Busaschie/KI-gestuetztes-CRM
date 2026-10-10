import os

# Tests laufen ohne .env-Pflichtwerte
os.environ.setdefault("DJANGO_SECRET_KEY", "test")
os.environ.setdefault("DATABASE_URL", "postgres://sandra:sandra@localhost:5432/sandra_crm")
