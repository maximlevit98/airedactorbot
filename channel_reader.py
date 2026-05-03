import logging
import os

from telethon import TelegramClient
from telethon.tl.types import Message as TgMessage

logger = logging.getLogger(__name__)

SESSION_FILE = "session"
MAX_TOTAL_CHARS = 7000  # запас до лимита LIMIT_POSTS в handlers.py


def _get_client() -> TelegramClient:
    api_id = os.getenv("TELEGRAM_API_ID", "")
    api_hash = os.getenv("TELEGRAM_API_HASH", "")
    if not api_id or not api_hash:
        raise RuntimeError("Не заданы TELEGRAM_API_ID / TELEGRAM_API_HASH в .env")
    return TelegramClient(SESSION_FILE, int(api_id), api_hash)


async def fetch_posts(channel: str, limit: int = 60) -> list[str]:
    """
    Выгружает последние посты из канала.
    Пропускает короткие сообщения (< 80 символов) и стоп-кадры.
    Возвращает список текстов, суммарно не превышающих MAX_TOTAL_CHARS.
    """
    client = _get_client()
    await client.connect()

    if not await client.is_user_authorized():
        await client.disconnect()
        raise RuntimeError("session_missing")

    try:
        posts: list[str] = []
        total_chars = 0
        async for msg in client.iter_messages(channel, limit=limit):
            if not isinstance(msg, TgMessage):
                continue
            text = (msg.text or "").strip()
            if len(text) < 80:
                continue  # пропускаем служебные / слишком короткие
            if total_chars + len(text) > MAX_TOTAL_CHARS:
                break
            posts.append(text)
            total_chars += len(text)
        return posts
    finally:
        await client.disconnect()
