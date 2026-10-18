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
        params = {"timeout": timeout, "allowed_updates": ["message", "callback_query"]}
        if offset is not None:
            params["offset"] = offset
        return self._call("getUpdates", http_timeout=timeout + 10, **params)

    def set_commands(self, commands: list[tuple[str, str]]) -> None:
        """Befehlsmenü in der Telegram-App (Schaltfläche „Menü“ bzw. Vorschläge bei „/“)."""
        cmds = [{"command": c, "description": d} for c, d in commands]
        # Telegram zeigt die spezifischste Liste an: Standard UND „private Chats“ setzen,
        # sonst überdeckt eine ältere Liste (z. B. aus BotFather) die neue.
        self._call("setMyCommands", commands=cmds)
        self._call("setMyCommands", commands=cmds, scope={"type": "all_private_chats"})

    def send_message(self, chat_id: int, text: str, buttons: list[list[tuple[str, str]]] | None = None) -> dict:
        """buttons: Zeilen von (Beschriftung, callback_data) – erscheinen als Knöpfe unter der Nachricht."""
        params = {"chat_id": chat_id, "text": _shorten(text), "parse_mode": "HTML", "disable_web_page_preview": True}
        if buttons:
            params["reply_markup"] = _keyboard(buttons)
        return self._call("sendMessage", **params)

    def edit_message(self, chat_id: int, message_id: int, text: str,
                     buttons: list[list[tuple[str, str]]] | None = None) -> None:
        params = {"chat_id": chat_id, "message_id": message_id, "text": _shorten(text), "parse_mode": "HTML",
                  "disable_web_page_preview": True, "reply_markup": _keyboard(buttons or [])}
        try:
            self._call("editMessageText", **params)
        except TelegramError as e:
            if "message is not modified" not in str(e):
                raise

    def delete_message(self, chat_id: int, message_id: int) -> bool:
        """Löscht eine Nachricht (eigene oder – im privaten Chat – des Nutzers), nur bis 48 h nach dem Senden."""
        try:
            self._call("deleteMessage", chat_id=chat_id, message_id=message_id)
            return True
        except TelegramError:
            return False

    def answer_callback(self, callback_id: str, text: str = "") -> None:
        self._call("answerCallbackQuery", callback_query_id=callback_id, text=text)

    def download_file(self, file_id: str) -> tuple[bytes, str]:
        """Lädt eine Datei (z. B. Sprachnachricht) herunter. Gibt (Inhalt, Dateiname) zurück."""
        info = self._call("getFile", file_id=file_id)
        path = info["file_path"]
        try:
            resp = httpx.get(f"{API}/file/bot{self.token}/{path}", timeout=60)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise TelegramError(f"Download fehlgeschlagen: {type(e).__name__}") from e
        return resp.content, path.rsplit("/", 1)[-1]


def _shorten(text: str) -> str:
    return text if len(text) <= MAX_LEN else text[: MAX_LEN - 20] + "\n… (gekürzt)"


def _keyboard(buttons: list[list[tuple[str, str]]]) -> dict:
    return {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in row] for row in buttons]}
