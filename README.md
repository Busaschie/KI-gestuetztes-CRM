# Sandra CRM – Agentensystem

## Start
    python -m venv .venv && source .venv/bin/activate
    pip install -r requirements/dev.txt
    cp .env.example .env
    python manage.py makemigrations && python manage.py migrate
    python manage.py runserver
    celery -A config worker -l info   # zweites Terminal, Redis nötig

## Erweitern
- Neue Fach-App: `apps/<name>/` anlegen, in `LOCAL_APPS` eintragen, ggf. URL in `config/urls.py`.
- Neuer Agent: Klasse in `agents/workflows/` von `BaseAgent` ableiten, mit `@register` versehen.
- Neues Werkzeug für Agenten: `agents/tools/`. Prompts: `agents/llm/prompts/`.
