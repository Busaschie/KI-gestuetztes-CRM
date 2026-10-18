from pathlib import Path
import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent
env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])

DJANGO_APPS = [
    "unfold",  # Admin-Design – muss vor django.contrib.admin stehen
    "unfold.contrib.filters",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]
THIRD_PARTY_APPS = [
    "django_q",
]
LOCAL_APPS = [
    "apps.core",
    "apps.accounts",
    "apps.contacts",
    "apps.candidates",
    "apps.clients",
    "apps.jobs",
    "apps.pipeline",
    "apps.communications",
    "apps.privacy",
    "apps.bot",
]
INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]

# Pflicht: DATABASE_URL aus .env bzw. Umgebung (PostgreSQL). Kein stiller Rückfall auf SQLite.
DATABASES = {"default": env.db("DATABASE_URL")}
AUTH_USER_MODEL = "accounts.User"

LANGUAGE_CODE = "de-de"
TIME_ZONE = env("TIME_ZONE", default="Europe/Bucharest")  # Sandra arbeitet in Rumänien; lokal z. B. Europe/Berlin
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Hintergrundaufgaben: django-q2 mit PostgreSQL als Warteschlange (kein Redis)
Q_CLUSTER = {
    "name": "sandra_crm",
    "orm": "default",
    "workers": 2,
    "timeout": 2000,  # Sekunden pro Aufgabe – über OLLAMA_TIMEOUT, lokales Modell kann langsam sein
    "retry": 2100,    # muss größer als timeout sein
    "catch_up": False,
}
# CV-Postfach (IMAP, febas) – Zugangsdaten nur in der .env
IMAP_HOST = env("IMAP_HOST", default="")
IMAP_PORT = env.int("IMAP_PORT", default=993)
IMAP_SSL = env.bool("IMAP_SSL", default=True)
IMAP_USER = env("IMAP_USER", default="")
IMAP_PASSWORD = env("IMAP_PASSWORD", default="")
IMAP_FOLDER = env("IMAP_FOLDER", default="INBOX")
IMAP_PROCESSED_FOLDER = env("IMAP_PROCESSED_FOLDER", default="")  # leer = nur als gelesen markieren

# Versand-Postfach (SMTP) – getrennt vom CV-Postfach; für Profile, Absagen usw. (Verträge verschickt Documenso)
EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")  # lokal: Ausgabe im Terminal
EMAIL_HOST = env("EMAIL_HOST", default="")
EMAIL_PORT = env.int("EMAIL_PORT", default=465)
EMAIL_USE_SSL = env.bool("EMAIL_USE_SSL", default=True)  # 465 = SSL, 587 = STARTTLS (dann EMAIL_USE_TLS=True)
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=False)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_TIMEOUT = 30
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="")
EMAIL_REPLY_TO = env.list("EMAIL_REPLY_TO", default=[])  # Antworten an Sandra
OUTBOUND_STOP_MINUTES = env.int("OUTBOUND_STOP_MINUTES", default=60)  # Stopp-Fenster für Profilversand; 0 = sofort

# Standardabsage (P1 Punkt 7) – erst nach Rechtsprüfung (Art. 22 DSGVO) im Betrieb einschalten
STANDARD_REJECTION_ENABLED = env.bool("STANDARD_REJECTION_ENABLED", default=False)
STANDARD_REJECTION_DAYS = env.int("STANDARD_REJECTION_DAYS", default=10)  # Tage nach Zuordnung zum Auftrag
STANDARD_REJECTION_TIME = env("STANDARD_REJECTION_TIME", default="10:00")  # Versand am Folgetag (Ortszeit)
STANDARD_REJECTION_PREPARE_TIME = env("STANDARD_REJECTION_PREPARE_TIME", default="07:25")  # Planung, vor dem Briefing

MEDIA_URL = "media/"
MEDIA_ROOT = env("MEDIA_ROOT", default=str(BASE_DIR / "media"))  # CV-Originale (später EU-Objektspeicher)

# Sprachmodell – austauschbar (siehe work/entscheidungen.md)
LLM_PROVIDER = env("LLM_PROVIDER", default="ollama")  # mistral | ollama | fake
MISTRAL_API_KEY = env("MISTRAL_API_KEY", default="")
MISTRAL_MODEL = env("MISTRAL_MODEL", default="mistral-small-latest")
MISTRAL_OCR_MODEL = env("MISTRAL_OCR_MODEL", default="mistral-ocr-latest")
MISTRAL_MAX_TOKENS = env.int("MISTRAL_MAX_TOKENS", default=4096)  # max. Antwortlänge (zählt gegen Tokens/Minute)
OLLAMA_URL = env("OLLAMA_URL", default="http://localhost:11434")
OLLAMA_MODEL = env("OLLAMA_MODEL", default="qwen3:8b")
OLLAMA_TIMEOUT = env.int("OLLAMA_TIMEOUT", default=1800)  # Gesamtdauer pro CV in Sekunden (Antwort wird gestreamt)
OLLAMA_NUM_CTX = env.int("OLLAMA_NUM_CTX", default=16384)  # Kontextgröße in Tokens
OLLAMA_NUM_PREDICT = env.int("OLLAMA_NUM_PREDICT", default=4096)  # max. Antwortlänge in Tokens

# E-Signatur – austauschbar (documenso | fake). Zugangsdaten nur in der .env
SIGNATURE_PROVIDER = env("SIGNATURE_PROVIDER", default="fake")
DOCUMENSO_API_URL = env("DOCUMENSO_API_URL", default="http://localhost:3001/api/v2")
DOCUMENSO_API_KEY = env("DOCUMENSO_API_KEY", default="")
DOCUMENSO_WEBHOOK_SECRET = env("DOCUMENSO_WEBHOOK_SECRET", default="")  # Header X-Documenso-Secret

# Telegram-Bot – Kanal zu Sandra. Token nur in der .env
TELEGRAM_BOT_TOKEN = env("TELEGRAM_BOT_TOKEN", default="")
TELEGRAM_ALLOWED_CHAT_IDS = env.list("TELEGRAM_ALLOWED_CHAT_IDS", cast=int, default=[])  # leer = niemand freigeschaltet
TELEGRAM_BRIEFING_TIME = env("TELEGRAM_BRIEFING_TIME", default="07:30")  # Ortszeit (TIME_ZONE)
TELEGRAM_ASYNC = env.bool("TELEGRAM_ASYNC", default=False)  # True = Verarbeitung über qcluster (Bot bleibt reaktionsfähig)

# Sprache → Text (Sprachnachrichten): mistral (Betrieb, EU) | whisper (lokal) | fake
TRANSCRIBE_PROVIDER = env("TRANSCRIBE_PROVIDER", default="whisper")
TRANSCRIBE_LANGUAGE = env("TRANSCRIBE_LANGUAGE", default="")  # leer = automatisch erkennen (de/ro/en)
MISTRAL_TRANSCRIBE_MODEL = env("MISTRAL_TRANSCRIBE_MODEL", default="voxtral-mini-latest")
TRANSCRIBE_NAME_HINTS = env.int("TRANSCRIBE_NAME_HINTS", default=50)  # zuletzt bearbeitete Personen als Namenshinweis
WHISPER_MODEL = env("WHISPER_MODEL", default="small")  # tiny | base | small | medium – größer = genauer, langsamer

# Verträge: Stopp-Fenster vor dem Versand und Erinnerungen an den Kunden (P1 Punkt 4)
CONTRACT_STOP_MINUTES = env.int("CONTRACT_STOP_MINUTES", default=60)  # 0 = sofort senden
CONTRACT_REMINDER_DAYS = env.list("CONTRACT_REMINDER_DAYS", cast=int, default=[3, 7])  # Tage nach Versand
CONTRACT_REMINDER_TIME = env("CONTRACT_REMINDER_TIME", default="09:00")  # tägliche Prüfung (Ortszeit)

# Vertrags-PDF: Daten der Auftragnehmerin (Sandra) – nur in der .env, nicht im Repository
CONTRACTOR_NAME = env("CONTRACTOR_NAME", default="")
CONTRACTOR_ADDRESS = env("CONTRACTOR_ADDRESS", default="")  # Zeilen mit „|“ getrennt
CONTRACTOR_TAX_ID = env("CONTRACTOR_TAX_ID", default="")  # z. B. „CUI: …“
CONTRACTOR_SIGNER = env("CONTRACTOR_SIGNER", default="")  # Name in Text und Unterschriftszeile
CONTRACT_GOVERNING_LAW = env("CONTRACT_GOVERNING_LAW", default="österreichisches Recht")  # offen: je Land? (felder.md)

# Admin-Design (django-unfold) – Farben aus Sandras Logo (#C6122F), Seitenleiste nach Arbeitsbereichen
from django.templatetags.static import static  # noqa: E402
from django.urls import reverse, reverse_lazy  # noqa: E402


def _nav(title, icon, url):
    return {"title": title, "icon": icon, "link": reverse_lazy(url)}


UNFOLD = {
    "SITE_TITLE": "Sandra CRM",
    "SITE_HEADER": "Sandra CRM",
    "SITE_SUBHEADER": "Headhunting",
    "SITE_ICON": lambda request: static("contract/logo.png"),
    "SITE_FAVICONS": [{"rel": "icon", "type": "image/png", "href": lambda request: static("contract/logo.png")}],
    "SHOW_VIEW_ON_SITE": False,
    "COLORS": {
        "primary": {
            "50": "oklch(97.1% .013 22)",
            "100": "oklch(93.6% .032 22)",
            "200": "oklch(88.5% .062 22)",
            "300": "oklch(80.8% .114 22)",
            "400": "oklch(70.4% .17 22)",
            "500": "oklch(61% .2 22)",
            "600": "oklch(52.7% .205 22)",  # Logofarbe
            "700": "oklch(46% .18 22)",
            "800": "oklch(40% .155 22)",
            "900": "oklch(35% .13 22)",
            "950": "oklch(24% .09 22)",
        },
    },
    "SIDEBAR": {
        "show_search": True,
        "show_all_applications": True,
        "navigation": [
            {"title": "Kandidaten", "items": [
                _nav("Kandidaten", "person_search", "admin:candidates_candidateprofile_changelist"),
                _nav("Dubletten", "content_copy", "admin:candidates_duplicatesuggestion_changelist"),
            ]},
            {"title": "Kunden & Aufträge", "items": [
                {"title": "Ansprechpartner", "icon": "badge",
                 "link": lambda request: reverse("admin:contacts_person_changelist") + "?rolle=kunde"},
                _nav("Firmen", "apartment", "admin:contacts_company_changelist"),
                _nav("Aufträge", "work", "admin:jobs_mandate_changelist"),
                _nav("Kandidaten in Aufträgen", "send", "admin:pipeline_submission_changelist"),
                _nav("Verträge", "contract", "admin:clients_contract_changelist"),
                _nav("Honorarmodelle", "percent", "admin:clients_feemodel_changelist"),
            ]},
            {"title": "Kommunikation", "items": [
                _nav("Wiedervorlagen", "event", "admin:communications_followup_changelist"),
                _nav("Notizen", "sticky_note_2", "admin:communications_note_changelist"),
                _nav("Eingang", "inbox", "admin:communications_inbounditem_changelist"),
                _nav("Ausgang", "outbox", "admin:communications_outboundmessage_changelist"),
                _nav("Bot-Entwürfe", "smart_toy", "admin:bot_botdraft_changelist"),
            ]},
            {"title": "Kontakte", "items": [
                _nav("Alle Personen", "contacts", "admin:contacts_person_changelist"),
            ]},
            {"title": "Datenschutz & System", "collapsible": True, "items": [
                _nav("Einwilligungen", "verified_user", "admin:privacy_consent_changelist"),
                _nav("Betroffenenanfragen", "gavel", "admin:privacy_datasubjectrequest_changelist"),
                _nav("Benutzer", "manage_accounts", "admin:accounts_user_changelist"),
                _nav("Zeitpläne", "schedule", "admin:django_q_schedule_changelist"),
                _nav("Fehlgeschlagene Aufgaben", "error", "admin:django_q_failure_changelist"),
            ]},
        ],
    },
}
