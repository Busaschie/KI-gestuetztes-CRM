"""Etappe 2: Sprach-/Textnachricht → Vorschlag → Bestätigung per Knopf → Notiz/Wiedervorlage."""
from datetime import date, timedelta

import pytest

from agents.llm.providers.fake import FakeProvider
from agents.llm.transcribe import FakeTranscriber
from apps.bot.extract import extract_note, find_persons
from apps.bot.handlers import handle_update
from apps.bot.models import BotDraft
from apps.communications.models import FollowUp, InboundItem, Note
from apps.contacts.models import Company, Employment, Person

ME = 4711


class FakeClient:
    def __init__(self):
        self.sent, self.edits, self.answers = [], [], []

    def send_message(self, chat_id, text, buttons=None):
        self.sent.append((chat_id, text, buttons))
        return {"message_id": 100 + len(self.sent)}

    def edit_message(self, chat_id, message_id, text, buttons=None):
        self.edits.append((message_id, text, buttons))

    def answer_callback(self, callback_id, text=""):
        self.answers.append(text)

    def download_file(self, file_id):
        return b"OggS-fake-audio", "file_1.oga"

    def buttons(self):
        """callback_data aller Knöpfe der letzten Nachricht/Bearbeitung."""
        last = (self.edits[-1][2] if self.edits else None) or self.sent[-1][2] or []
        return [d for row in last for _, d in row]


@pytest.fixture(autouse=True)
def bot_settings(settings, tmp_path):
    settings.TELEGRAM_ALLOWED_CHAT_IDS = [ME]
    settings.TELEGRAM_BOT_TOKEN = "test"
    settings.TELEGRAM_ASYNC = False
    settings.LLM_PROVIDER = "fake"
    settings.TRANSCRIBE_PROVIDER = "fake"
    settings.MEDIA_ROOT = str(tmp_path)


@pytest.fixture
def llm(monkeypatch):
    def set_answer(**answer):
        monkeypatch.setattr(FakeProvider, "response", {
            "person_name": None, "company": None, "note": "", "follow_up_date": None, "follow_up_text": None, **answer})
    return set_answer


@pytest.fixture
def meier(db):
    p = Person.objects.create(first_name="Eva", last_name="Meier")
    Employment.objects.create(person=p, company=Company.objects.create(name="Muster AG"), title="CFO")
    return p


def msg_update(message_id=1, **msg):
    return {"update_id": message_id, "message": {"message_id": message_id, "chat": {"id": ME},
                                                 "from": {"first_name": "Niko"}, **msg}}


def press(client, data, update_id=999):
    handle_update({"update_id": update_id, "callback_query": {
        "id": "cb", "data": data, "message": {"message_id": 1, "chat": {"id": ME}}}}, client)


# --- Ablauf ---------------------------------------------------------------------------------------

def test_voice_to_note_and_follow_up(meier, llm, monkeypatch):
    monkeypatch.setattr(FakeTranscriber, "text", "Mit Eva Meier telefoniert, nächste Woche zurückrufen")
    llm(person_name="Eva Meier", note="Telefoniert, will Rückruf.", follow_up_date="2099-01-01")  # unplausibel → weg
    client = FakeClient()
    handle_update(msg_update(voice={"file_id": "f1", "duration": 4}), client)

    item = InboundItem.objects.get()
    assert item.channel == InboundItem.Channel.VOICE and item.attachment
    assert item.raw_text.startswith("Mit Eva Meier")
    assert "Eva Meier" in FakeTranscriber.last_hints  # bekannte Namen werden als Hinweis übergeben
    draft = BotDraft.objects.get()
    assert draft.status == BotDraft.Status.AWAITING and draft.person == meier
    assert "Eva Meier – Muster AG" in client.sent[-1][1]
    assert not Note.objects.exists()  # erst nach Bestätigung

    press(client, f"d{draft.pk}:ok")
    note = Note.objects.get()
    assert note.person == meier and note.text == "Telefoniert, will Rückruf."
    assert not FollowUp.objects.exists()  # Datum 2099 verworfen
    item.refresh_from_db()
    assert item.status == InboundItem.Status.ASSIGNED and item.person == meier
    assert "Gespeichert" in client.edits[-1][1]


def test_text_with_follow_up(meier, llm):
    today = date.today()
    due = today.replace(year=today.year + 1) if today.month != 2 or today.day != 29 else today
    llm(person_name="Meier", note="Will Angebot.", follow_up_date=due.isoformat(), follow_up_text="Angebot schicken")
    client = FakeClient()
    handle_update(msg_update(text="Meier will Angebot, in einem Jahr nachfassen"), client)
    draft = BotDraft.objects.get()
    press(client, f"d{draft.pk}:ok")
    fu = FollowUp.objects.get()
    assert fu.person == meier and fu.due_date == due and fu.text == "Angebot schicken"
    assert fu.source_note == Note.objects.get()


def test_choose_between_several_persons(db, llm):
    a = Person.objects.create(first_name="Eva", last_name="Meier")
    b = Person.objects.create(first_name="Jan", last_name="Meier")
    llm(person_name="Meier", note="Kurz gesprochen.")
    client = FakeClient()
    handle_update(msg_update(text="Mit Meier gesprochen"), client)
    draft = BotDraft.objects.get()
    assert draft.person is None and set(draft.candidates) == {a.pk, b.pk}
    assert f"d{draft.pk}:p{b.pk}" in client.buttons() and f"d{draft.pk}:ok" not in client.buttons()

    press(client, f"d{draft.pk}:p{b.pk}")
    assert f"d{draft.pk}:ok" in client.buttons()
    press(client, f"d{draft.pk}:ok", update_id=1000)
    assert Note.objects.get().person == b


def test_save_without_person(db, llm):
    llm(person_name="Unbekannt Niemand", note="Neuer Kontakt.", follow_up_date=date.today().isoformat(),
        follow_up_text="Anrufen")
    client = FakeClient()
    handle_update(msg_update(text="Neuer Kontakt Niemand, heute anrufen"), client)
    draft = BotDraft.objects.get()
    assert "nicht in der Datenbank" in client.sent[-1][1]
    press(client, f"d{draft.pk}:np")
    assert not Note.objects.exists()
    fu = FollowUp.objects.get()
    assert fu.person is None and "Unbekannt Niemand" in fu.text
    assert InboundItem.objects.get().status == InboundItem.Status.UNASSIGNED


def test_cancel_and_double_press(meier, llm):
    llm(person_name="Eva Meier", note="x")
    client = FakeClient()
    handle_update(msg_update(text="Eva Meier x"), client)
    draft = BotDraft.objects.get()
    press(client, f"d{draft.pk}:x")
    press(client, f"d{draft.pk}:ok", update_id=1001)
    assert not Note.objects.exists()
    assert InboundItem.objects.get().status == InboundItem.Status.IGNORED
    assert "Bereits erledigt" in client.answers[-1]


def test_redelivered_message_processed_once(meier, llm):
    llm(person_name="Eva Meier", note="x")
    client = FakeClient()
    handle_update(msg_update(text="Eva Meier"), client)
    handle_update(msg_update(text="Eva Meier"), client)
    assert BotDraft.objects.count() == 1 and InboundItem.objects.count() == 1


def test_empty_transcript_fails_gracefully(db, llm, monkeypatch):
    monkeypatch.setattr(FakeTranscriber, "text", "")
    client = FakeClient()
    handle_update(msg_update(voice={"file_id": "f1", "duration": 1}), client)
    assert BotDraft.objects.get().status == BotDraft.Status.FAILED
    item = InboundItem.objects.get()
    assert item.status == InboundItem.Status.FAILED and "Keine Sprache" in item.error
    assert "⚠️" in client.sent[-1][1]


def test_foreign_chat_cannot_press_buttons(meier, llm):
    llm(person_name="Eva Meier", note="x")
    client = FakeClient()
    handle_update(msg_update(text="Eva Meier"), client)
    draft = BotDraft.objects.get()
    handle_update({"update_id": 5, "callback_query": {"id": "cb", "data": f"d{draft.pk}:ok",
                                                      "message": {"message_id": 1, "chat": {"id": 999}}}}, client)
    assert not Note.objects.exists()


# --- Bausteine ------------------------------------------------------------------------------------

def test_find_persons_tolerates_spelling(meier):
    Person.objects.create(first_name="Paul", last_name="Schulz")
    assert find_persons("Eva Maier") == [meier]
    assert find_persons("Meier", "Muster AG") == [meier]
    assert find_persons("Schmidt") == []
    assert find_persons(None) == []


def test_extract_cleans_answer(db, llm):
    llm(person_name="null", note="", follow_up_date="kein Datum", follow_up_text="x")
    data = extract_note("Nur ein Gedanke", today=date(2026, 10, 13))
    assert data == {"person_name": None, "company": None, "note": "Nur ein Gedanke",
                    "follow_up_date": None, "follow_up_text": None}


# --- Etappe 3: Fehlerfälle, Datum, /offen, /status --------------------------------------------------

def test_shift_follow_up_buttons(meier, llm):
    llm(person_name="Eva Meier", note="Rückruf")
    client = FakeClient()
    handle_update(msg_update(text="Eva Meier Rückruf"), client)
    draft = BotDraft.objects.get()
    assert f"d{draft.pk}:f7" in client.buttons() and f"d{draft.pk}:f0" not in client.buttons()

    press(client, f"d{draft.pk}:f7")
    draft.refresh_from_db()
    assert draft.data["follow_up_date"] == (date.today() + timedelta(days=7)).isoformat()
    assert draft.data["follow_up_text"] == "Rückruf"
    press(client, f"d{draft.pk}:f1", update_id=1002)
    draft.refresh_from_db()
    assert draft.data["follow_up_date"] == (date.today() + timedelta(days=8)).isoformat()
    press(client, f"d{draft.pk}:f0", update_id=1003)
    press(client, f"d{draft.pk}:ok", update_id=1004)
    assert Note.objects.exists() and not FollowUp.objects.exists()


def test_recover_stuck_and_retry(meier, llm):
    from apps.bot.processing import recover_stuck

    llm(person_name="Eva Meier", note="Nach Neustart")
    item = InboundItem.objects.create(channel=InboundItem.Channel.TELEGRAM, raw_text="Eva Meier", external_id="x1")
    draft = BotDraft.objects.create(chat_id=ME, inbound=item)  # hängt in „In Verarbeitung“
    client = FakeClient()
    assert recover_stuck(client) == 1
    draft.refresh_from_db()
    assert draft.status == BotDraft.Status.FAILED and "unterbrochen" in client.sent[-1][1]
    assert f"d{draft.pk}:retry" in client.buttons()

    press(client, f"d{draft.pk}:retry")
    draft.refresh_from_db()
    assert draft.status == BotDraft.Status.AWAITING and draft.person == meier


def test_send_failure_keeps_draft_for_offen(meier, llm):
    from apps.bot.telegram import TelegramError

    class FlakyClient(FakeClient):
        fail = True

        def send_message(self, chat_id, text, buttons=None):
            if self.fail and buttons:
                raise TelegramError("Telegram nicht erreichbar")
            return super().send_message(chat_id, text, buttons)

    llm(person_name="Eva Meier", note="x")
    client = FlakyClient()
    handle_update(msg_update(text="Eva Meier x"), client)
    draft = BotDraft.objects.get()
    assert draft.status == BotDraft.Status.AWAITING and draft.message_id is None

    client.fail = False
    handle_update(msg_update(message_id=2, text="/offen"), client)
    assert "1 offene Vorschläge" in client.sent[-2][1]
    assert f"d{draft.pk}:ok" in client.buttons()


def test_offen_empty_and_status(db):
    client = FakeClient()
    handle_update(msg_update(text="/offen"), client)
    handle_update(msg_update(message_id=2, text="/status"), client)
    assert "Keine offenen" in client.sent[0][1]
    assert "Spracherkennung: fake" in client.sent[1][1] and "Briefing täglich" in client.sent[1][1]


def test_confirmation_also_sent_at_bottom(meier, llm):
    llm(person_name="Eva Meier", note="Vorlage senden")
    client = FakeClient()
    handle_update(msg_update(text="Eva Meier Vorlage"), client)
    press(client, f"d{BotDraft.objects.get().pk}:ok")
    assert client.sent[-1][1].startswith("✅ Gespeichert") and "Eva Meier" in client.sent[-1][1]
