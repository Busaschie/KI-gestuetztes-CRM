# Sandra CRM – Agentensystem

Planung und Entscheidungen: `../work/` (uebersicht.md, entscheidungen.md, technik.md).

## Start (Windows, PyCharm-Terminal)
    python -m venv .venv
    .venv\Scripts\activate
    pip install -r requirements\dev.txt
    copy .env.example .env
    docker compose up -d                 # PostgreSQL + pgvector
    python manage.py migrate
    python manage.py createsuperuser
    python manage.py runserver           # Admin: http://127.0.0.1:8000/admin/
    python manage.py qcluster            # zweites Terminal: Hintergrundprozess (django-q2)
    python manage.py test_agent "Hallo"  # drittes Terminal: Test der Warteschlange
    pytest                               # Tests (ohne Netz, Fake-Sprachmodell)

## Lebensläufe einlesen
    python manage.py import_cv ..\testdaten\cvs           # über die Warteschlange (qcluster muss laufen)
    python manage.py import_cv pfad\zu\cv.pdf --sync      # sofort, ohne Warteschlange

Ergebnis im Admin unter **Eingänge** (Status, Fehler) und **Personen / Kandidatenprofile**.
Sprachmodell in `.env`: `LLM_PROVIDER=ollama` (lokal, z. B. `ollama pull qwen3:8b`) oder `mistral` (+ `MISTRAL_API_KEY`).
Gescannte PDFs brauchen die Mistral-Texterkennung (OCR). Testdaten nie ins Repository legen.

## Aufbau
- `apps/contacts` – Person, Unternehmen, Beschäftigung, Herkunft (gemeinsame Basis)
- `apps/candidates` – Kandidatenprofil, CV-Versionen, Dubletten-Vorschläge
- `apps/jobs` – Aufträge (Mandate)
- `apps/clients` – Honorarmodelle, Verträge (harte Sperre: `Mandate.has_signed_contract`)
- `apps/pipeline` – Kandidat ↔ Auftrag, Status, Zustimmung zur Vorstellung
- `apps/communications` – Notizen, Wiedervorlagen, Eingänge, ausgehende Nachrichten
- `apps/privacy` – Einwilligungen, Betroffenenanfragen
- `agents/` – KI-Agenten; Warteschlange über django-q2 auf PostgreSQL (kein Redis)
  - `agents/llm/` – austauschbare Sprachmodelle (Mistral, Ollama, Fake für Tests), Schema und Prompts
  - `agents/tools/text_extract.py` – Text aus PDF/Word, Scans per OCR
  - `agents/workflows/cv_parser.py` – Agent für die CV-Auslese

## Erweitern
- Neue Fach-App: `apps/<name>/` anlegen, in `LOCAL_APPS` eintragen, ggf. URL in `config/urls.py`.
- Neuer Agent: Datei in `agents/workflows/`, Klasse von `BaseAgent` ableiten, `@register` – wird automatisch geladen.
- Agent starten: `from agents.tasks import enqueue_agent; enqueue_agent("name", ...)`.
