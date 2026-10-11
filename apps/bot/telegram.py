"""Schlanker Client für die Telegram-Bot-API (nur was wir brauchen, ohne Zusatzbibliothek)."""
import httpx
from django.conf import settings

API = "https://api.telegram.org"
MAX_LEN = 4000  # Telegram erlaubt 4096 Zeichen pro Nachricht


class TelegramError(Exception):
    pass


class TelegramClient:
    def __init__(self, token: str | None = None, timeout: float = 30):
        self.token = token or settings.TELEGRAM_BOT_TOKEN
        if not self.token:
            raise TelegramError("TELEGRAM_BOT_TOKEN fehlt in der .env")
        self.timeout = timeout

    def _call(self, method: str, http_timeout: float | None = None, **params):
        try:
            resp = httpx.post(f"{API}/bot{self.token}/{method}", json=params, timeout=http_timeout or self.timeout)
            data = resp.json()
        except (httpx.HTTPError, ValueError) as e:
            raise TelegramError(f"Telegram nicht erreichbar ({method}): {type(e).__name__}") from e
        if not data.get("ok"):
            raise TelegramError(f"Telegram {method}: {data.get('description', 'unbekannter Fehler')}")
        return data["result"]

    def get_me(self) -> dict:
        return self._call("getMe")

    def get_updates(self, offset: int | None = None, timeout: int = 50) -> list[dict]:
        params = {"timeout": timeout, "allowed_updates": ["message"]}
        if offset is not None:
            params["offset"] = offset
        return self._call("getUpdates", http_timeout=timeout + 10, **params)

    def set_commands(self, commands: list[tuple[str, str]]) -> None:
        """Befehlsmenü in der Telegram-App (Schaltfläche „Menü“ bzw. Vorschläge bei „/“)."""
        self._call("setMyCommands", commands=[{"command": c, "description": d} for c, d in commands])

    def send_message(self, chat_id: int, text: str) -> None:
        if len(text) > MAX_LEN:
            text = text[: MAX_LEN - 20] + "\n… (gekürzt)"
        self._call("sendMessage", chat_id=chat_id, text=text, parse_mode="HTML", disable_web_page_preview=True)
