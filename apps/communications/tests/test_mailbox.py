from email.message import EmailMessage

import pytest

from apps.communications.mailbox import fetch_mailbox
from apps.communications.models import InboundItem


class FakeIMAP:
    """Minimaler IMAP-Server im Speicher: UID → (Rohmail, Flags)."""

    def __init__(self, mails, move_ok=True):
        self.mails = {str(i + 1).encode(): [raw, set()] for i, raw in enumerate(mails)}
        self.moved, self.move_ok = [], move_ok

    def select(self, folder):
        return "OK", [b"1"]

    def uid(self, cmd, *args):
        if cmd == "SEARCH":
            return "OK", [b" ".join(u for u, (_, f) in self.mails.items() if "\\Seen" not in f)]
        if cmd == "FETCH":
            return "OK", [(b"1 (BODY[] ...)", self.mails[args[0]][0])]
        if cmd == "STORE":
            self.mails[args[0]][1].add("\\Seen")
            return "OK", []
        if cmd == "MOVE":
            if not self.move_ok:
                return "NO", []
            self.moved.append(args[0])
            self.mails[args[0]][1].add("\\Seen")
            return "OK", []
        raise AssertionError(cmd)


def mail(msg_id, subject="Bewerbung", attachments=(), body="Hallo"):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"], m["Message-ID"] = "jobs@stepstone.example", "cv@kohlweg.de", subject, msg_id
    m.set_content(body)
    for name, data, mime in attachments:
        maintype, subtype = mime.split("/")
        m.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    return m.as_bytes()


PDF = ("Lebenslauf Anna Hötter.pdf", b"%PDF-1.4 fake", "application/pdf")
DOCX = ("cv.docx", b"PK fake", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
IMG = ("foto.jpg", b"\xff\xd8 fake", "image/jpeg")


@pytest.fixture(autouse=True)
def media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    settings.IMAP_PROCESSED_FOLDER = ""


@pytest.mark.django_db
def test_cv_attachments_become_inbound_items_and_mail_is_marked_seen():
    imap = FakeIMAP([mail("<a@x>", "Bewerbung Vertrieb", [PDF, DOCX, IMG])])
    queued = []
    r = fetch_mailbox(conn=imap, enqueue=queued.append)
    assert (r.messages, r.attachments, r.without_cv) == (1, 2, 0)
    items = InboundItem.objects.order_by("pk")
    assert [i.subject for i in items] == ["Lebenslauf Anna Hötter.pdf", "cv.docx"]
    assert items[0].channel == "email" and items[0].sender == "jobs@stepstone.example"
    assert items[0].context == "Bewerbung Vertrieb" and items[0].external_id == "<a@x>#1"
    assert items[0].attachment.read() == b"%PDF-1.4 fake"
    assert len(queued) == 2 and "\\Seen" in imap.mails[b"1"][1]


@pytest.mark.django_db
def test_mail_without_cv_is_unassigned_with_body_for_the_briefing():
    imap = FakeIMAP([mail("<b@x>", "Neue Bewerbung", body="CV im Portal: https://portal.example/123")])
    r = fetch_mailbox(conn=imap, enqueue=lambda i: None)
    item = InboundItem.objects.get()
    assert r.without_cv == 1 and item.status == InboundItem.Status.UNASSIGNED
    assert "portal.example" in item.raw_text and "Jobportal" in item.error


@pytest.mark.django_db
def test_same_message_is_not_processed_twice():
    raw = mail("<c@x>", attachments=[PDF])
    fetch_mailbox(conn=FakeIMAP([raw]), enqueue=lambda i: None)
    r = fetch_mailbox(conn=FakeIMAP([raw]), enqueue=lambda i: None)  # z. B. von Hand wieder ungelesen markiert
    assert r.skipped == 1 and InboundItem.objects.count() == 1


@pytest.mark.django_db
def test_seen_mails_are_ignored():
    imap = FakeIMAP([mail("<d@x>", attachments=[PDF])])
    imap.mails[b"1"][1].add("\\Seen")
    assert fetch_mailbox(conn=imap, enqueue=lambda i: None).messages == 0


@pytest.mark.django_db
def test_move_to_processed_folder_with_fallback(settings):
    settings.IMAP_PROCESSED_FOLDER = "Verarbeitet"
    ok = FakeIMAP([mail("<e@x>", attachments=[PDF])])
    fetch_mailbox(conn=ok, enqueue=lambda i: None)
    assert ok.moved == [b"1"]
    fail = FakeIMAP([mail("<f@x>", attachments=[PDF])], move_ok=False)
    fetch_mailbox(conn=fail, enqueue=lambda i: None)
    assert fail.moved == [] and "\\Seen" in fail.mails[b"1"][1]


@pytest.mark.django_db
def test_path_in_attachment_name_is_stripped():
    evil = ("..\\..\\windows\\lebenslauf.pdf", b"%PDF", "application/pdf")
    fetch_mailbox(conn=FakeIMAP([mail("<g@x>", attachments=[evil])]), enqueue=lambda i: None)
    assert InboundItem.objects.get().subject == "lebenslauf.pdf"


def test_missing_credentials_give_clear_error(settings):
    from apps.communications.mailbox import connect

    settings.IMAP_HOST = ""
    with pytest.raises(RuntimeError, match="IMAP_HOST"):
        connect()


def test_scheduled_task_is_silent_without_configuration(settings):
    from apps.communications.tasks import fetch_cv_mailbox

    settings.IMAP_HOST = ""
    assert fetch_cv_mailbox() == {"skipped": "IMAP nicht konfiguriert"}


def test_connection_error_gives_clear_hint(settings, monkeypatch):
    import imaplib

    from apps.communications import mailbox

    settings.IMAP_HOST, settings.IMAP_USER, settings.IMAP_PORT = "imap.falsch.example", "u", 993

    def refuse(*a, **k):
        assert k.get("timeout") == mailbox.IMAP_TIMEOUT
        raise OSError("timed out")

    monkeypatch.setattr(imaplib, "IMAP4_SSL", refuse)
    with pytest.raises(RuntimeError, match="imap.falsch.example:993.*prüfen"):
        mailbox.connect()


@pytest.mark.django_db
def test_log_lines_are_written():
    lines = []
    fetch_mailbox(conn=FakeIMAP([mail("<h@x>", "Bewerbung", [PDF])]), enqueue=lambda i: None, log_line=lines.append)
    assert lines[0].startswith("Verbunden – 1 ungelesene") and "1 CV-Anhang" in lines[1]
