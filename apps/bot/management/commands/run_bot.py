"""Startet den Telegram-Bot per Long-Polling (Entwicklung und kleiner Server – kein öffentlicher Webhook nötig).

python manage.py run_bot      Beenden mit Strg+C
"""
import logging
import time

from django.core.management.base import BaseCommand, CommandError

from apps.bot.handlers import COMMANDS, handle_update, is_allowed
from apps.bot.telegram import TelegramClient, TelegramError

log = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Startet den Telegram-Bot (Long-Polling)"

    def handle(self, *args, **opts):
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
        for noisy in ("httpx", "httpcore", "faster_whisper"):
            logging.getLogger(noisy).setLevel(logging.WARNING)
        try:
            client = TelegramClient()
            me = client.get_me()
        except TelegramError as e:
            raise CommandError(str(e)) from e
        client.set_commands(COMMANDS)
        self.stdout.write(self.style.SUCCESS(f"Bot @{me['username']} läuft – Strg+C beendet."))

        try:
            self._loop(client)
        except KeyboardInterrupt:
            self.stdout.write("Bot beendet.")

    def _loop(self, client):
        offset = None
        while True:
            try:
                updates = client.get_updates(offset)
            except TelegramError as e:
                self.stderr.write(f"{e} – neuer Versuch in 10 s")
                time.sleep(10)
                continue
            for update in updates:
                offset = update["update_id"] + 1  # bestätigt die Nachricht bei Telegram
                self._show(update)
                try:
                    handle_update(update, client)
                except Exception as e:  # ein Fehler darf den Bot nicht stoppen
                    log.exception("Fehler bei Telegram-Update %s", update.get("update_id"))
                    self.stderr.write(f"  Fehler: {type(e).__name__}: {e}")

    def _show(self, update):
        """Kurze Konsolenausgabe je Nachricht – ohne Inhalt (Datenschutz), nur Typ und Chat-ID."""
        if cb := update.get("callback_query"):
            chat_id = ((cb.get("message") or {}).get("chat") or {}).get("id")
            self.stdout.write(f"Knopf: {cb.get('data', '')} von Chat {chat_id}")
            return
        msg = update.get("message") or {}
        chat_id = (msg.get("chat") or {}).get("id")
        kind = "Befehl " + msg["text"].split()[0] if msg.get("text", "").startswith("/") else \
            "Sprachnachricht" if "voice" in msg or "audio" in msg else "Text" if "text" in msg else "Sonstiges"
        state = "freigeschaltet" if chat_id and is_allowed(chat_id) else "nicht freigeschaltet"
        self.stdout.write(f"Eingang: {kind} von Chat {chat_id} ({state})")
