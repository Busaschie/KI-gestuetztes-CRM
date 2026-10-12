# Sandra CRM – Agentensystem

KI-gestütztes CRM für eine selbstständige Headhunterin: Lebensläufe kommen per E-Mail herein und werden automatisch ausgelesen, Verträge laufen über E-Signatur mit harter Versandsperre, und die Bedienung soll möglichst über einen Telegram-Bot laufen (Briefing, später Sprachnotizen).
Grundsatz: Nichts geht ohne Freigabe nach außen – Ausnahmen werden protokolliert.

Planung und Entscheidungen: `../work/` (uebersicht.md, entscheidungen.md, technik.md, verlauf.md).

## Technik
- Django 5.2 LTS, PostgreSQL + pgvector (lokal per Docker), django-q2 als Warteschlange in PostgreSQL (kein Redis/Celery)
- Sprachmodell austauschbar über `LLM_PROVIDER`: Mistral (Betrieb, EU), Ollama (lokal), Fake (Tests)
- E-Signatur austauschbar über `SIGNATURE_PROVIDER`: DocuSeal (Betrieb), Fake (Entwicklung/Tests)
- Telegram-Bot ohne Zusatzbibliothek (httpx, Long-Polling)
- Konfiguration nur über Umgebungsvariablen (`.env`, Vorlage `.env.example`)

## Stand
- [x] Datenmodell: Personen, Unternehmen, Kandidaten, Aufträge, Pipeline, Kommunikation, Datenschutz
- [x] CV-Auslese (PDF, Word, Scan) mit Schutzregeln, IMAP-Abruf des CV-Postfachs alle 5 min, Referenztest
- [x] Lesbare Profilansicht im Admin
- [x] Verträge über DocuSeal mit Webhook, Protokoll und harter Sperre für den Profilversand
- [x] Telegram-Bot Etappe 1: Zugriffsschutz, Befehle, Text → Eingang, tägliches Briefing
- [ ] Telegram-Bot Etappe 2: Sprachnachricht → Notiz/Wiedervorlage
- [ ] Stopp-Fenster und Erinnerungen beim Vertragsversand, DocuSeal-Livetest
- [ ] LinkedIn-Import, Kontaktpflege, Standardabsage

## Start (Windows, PyCharm-Terminal)
    python -m venv .venv
    .venv\Scripts\activate
    pip install -r requirements\dev.txt
    copy .env.example .env               # Werte eintragen, .env nie committen
    docker compose up -d                 # PostgreSQL + pgvector (Docker Desktop muss laufen)
    python manage.py migrate
    python manage.py createsuperuser
    python manage.py setup_schedules     # zeitgesteuerte Aufgaben (CV-Postfach, Briefing)
    python manage.py runserver           # Admin: http://127.0.0.1:8000/admin/
    python manage.py qcluster            # zweites Terminal: Hintergrundprozess (django-q2)
    python manage.py run_bot             # drittes Terminal: Telegram-Bot (optional)
    pytest                               # Tests (ohne Netz, Fake-Dienste)

## Lebensläufe einlesen
    python manage.py fetch_cvs                            # CV-Postfach sofort abrufen (sonst alle 5 min)
    python manage.py import_cv ..\testdaten\cvs           # Ordner über die Warteschlange (qcluster muss laufen)
    python manage.py import_cv pfad\zu\cv.pdf --sync      # sofort, ohne Warteschlange
    python manage.py cv_eval                              # Referenztest der Auslese

Ergebnis im Admin unter **Eingänge** (Status, Fehler) und **Kandidatenprofile**.
Gescannte PDFs brauchen die Mistral-Texterkennung (OCR). Echte Lebensläufe und Testdaten nie ins Repository legen.

## Verträge (E-Signatur)
1. Im Admin Vertrag zum Auftrag anlegen; bei Abweichungen von der Vorlage Aktion „Abweichungen freigeben“.
2. Aktion „Zur Unterschrift senden (DocuSeal)“ – Unterzeichner ist der eingetragene Unterzeichner oder der Ansprechpartner des Auftrags.
3. DocuSeal meldet Öffnen/Unterschrift/Ablehnung an `/clients/docuseal/webhook/` (Header `X-Docuseal-Secret` = `DOCUSEAL_WEBHOOK_SECRET`); das unterschriebene PDF wird in die eigene Ablage geladen.
4. Erst danach lässt sich „Profil an Kunden“ als ausgehende Nachricht freigeben oder senden – die Sperre sitzt im Modell und gilt überall.

Ohne DocuSeal-Konto testen (`SIGNATURE_PROVIDER=fake`):

    python manage.py contract_webhook <Vertrags-ID> form.completed

Die DocuSeal-Vorlage braucht eine Rolle (Standard „First Party“) und Felder mit den Namen
`Kunde`, `Position`, `Einsatzort`, `Honorar`, `Garantie`, `Abweichungen`, `Datum`.

## Telegram-Bot
1. Bot bei @BotFather anlegen (`/newbot`), Token als `TELEGRAM_BOT_TOKEN` in die `.env`.
2. `python manage.py run_bot` starten, dem Bot `/start` senden – er antwortet mit der Chat-ID.
3. Chat-ID in `TELEGRAM_ALLOWED_CHAT_IDS` eintragen (mehrere mit Komma), Bot neu starten.

Befehle: `/briefing`, `/id`, `/hilfe`. Textnachrichten werden als Eingang gespeichert.
Das tägliche Briefing (fällige Wiedervorlagen, nicht Zugeordnetes, Verträge ohne Unterschrift) kommt zur Uhrzeit `TELEGRAM_BRIEFING_TIME`, sofern `qcluster` läuft.
Nachrichten anderer Chat-IDs werden ignoriert (nur `/start` und `/id` werden beantwortet).

## Datenschutz
- Hochgeladene Dateien (CVs, Verträge) liefert `/media/…` nur an angemeldete Mitarbeiter aus.
- Die CV-Auslese speichert keine geschützten Merkmale; Sprachen werden nur übernommen, wenn sie im CV stehen.
- Geheimnisse (API-Schlüssel, Token, Passwörter) nur in der `.env`.

## Aufbau
- `apps/contacts` – Person, Unternehmen, Beschäftigung, Herkunft (gemeinsame Basis)
- `apps/candidates` – Kandidatenprofil, CV-Versionen, Dubletten-Vorschläge, Profilansicht im Admin
- `apps/jobs` – Aufträge (Mandate)
- `apps/clients` – Honorarmodelle, Verträge, Vertragsprotokoll, E-Signatur (`signature/`), Webhook
- `apps/pipeline` – Kandidat ↔ Auftrag, Status, Zustimmung zur Vorstellung
- `apps/communications` – Notizen, Wiedervorlagen, Eingänge, ausgehende Nachrichten (mit Vertragssperre)
- `apps/privacy` – Einwilligungen, Betroffenenanfragen
- `apps/bot` – Telegram-Bot: Client, Befehle, Briefing
- `apps/core` – Basismodelle, geschützte Media-Auslieferung
- `agents/` – KI-Agenten; Warteschlange über django-q2
  - `agents/llm/` – austauschbare Sprachmodelle (Mistral, Ollama, Fake), Schema und Prompts
  - `agents/tools/text_extract.py` – Text aus PDF/Word, Scans per OCR
  - `agents/workflows/cv_parser.py` – Agent für die CV-Auslese

## Befehle (Übersicht)
| Befehl | Zweck |
|---|---|
| `setup_schedules` | Zeitgesteuerte Aufgaben anlegen/aktualisieren |
| `fetch_cvs` | CV-Postfach abrufen |
| `import_cv` | Lebensläufe aus Datei/Ordner einlesen |
| `cv_debug` / `cv_eval` | Auslese eines CVs prüfen / Referenztest |
| `contract_webhook` | DocuSeal-Ereignis simulieren |
| `run_bot` | Telegram-Bot starten |
| `test_agent` | Warteschlange mit Test-Agent prüfen |

## Erweitern
- Neue Fach-App: `apps/<name>/` anlegen, in `LOCAL_APPS` eintragen, ggf. URL in `config/urls.py`.
- Neuer Agent: Datei in `agents/workflows/`, Klasse von `BaseAgent` ableiten, `@register` – wird automatisch geladen.
- Agent starten: `from agents.tasks import enqueue_agent; enqueue_agent("name", ...)`.
