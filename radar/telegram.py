"""Telegram Bot API helpers. Token/chat id come from the environment only."""
import os

import requests

from .util import safe_err


class TelegramError(Exception):
    pass


def _cfg():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        raise TelegramError("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set")
    return token, chat


def _call(method: str, payload: dict, timeout: int = 30) -> dict:
    token, _ = _cfg()
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/{method}", json=payload, timeout=timeout)
        data = r.json()
    except Exception as e:  # noqa: BLE001  (never include the URL: it contains the token)
        raise TelegramError(f"{method} failed ({safe_err(e)})") from None
    if not data.get("ok"):
        raise TelegramError(f"{method} rejected: {data.get('description', r.status_code)}")
    return data["result"]


def send(text: str, buttons: list[list[dict]] | None = None) -> dict:
    _, chat = _cfg()
    payload = {
        "chat_id": chat,
        "text": text[:4090],
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if buttons:
        payload["reply_markup"] = {"inline_keyboard": buttons}
    return _call("sendMessage", payload)


def get_updates(offset: int) -> list[dict]:
    return _call("getUpdates", {"offset": offset, "timeout": 0, "allowed_updates": ["callback_query"]})


def answer_callback(cb_id: str, text: str) -> None:
    try:
        _call("answerCallbackQuery", {"callback_query_id": cb_id, "text": text})
    except TelegramError:
        pass  # callbacks older than a minute can't be answered; harmless


def mark_message(chat_id, message_id, label: str, url: str | None) -> None:
    """Replace the 👍/👎 buttons with a single confirmation label (best effort)."""
    row = [{"text": label, "callback_data": "noop"}]
    kb = [row]
    if url:
        kb.append([{"text": "🔗 Open post", "url": url}])
    try:
        _call("editMessageReplyMarkup", {
            "chat_id": chat_id, "message_id": message_id, "reply_markup": {"inline_keyboard": kb},
        })
    except TelegramError:
        pass
