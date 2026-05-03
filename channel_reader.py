"""
Чтение постов из публичного Telegram-канала через веб-превью t.me/s/.
Не требует API_ID, API_HASH или авторизации — работает для любого публичного канала.
"""
import logging

import aiohttp
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

MAX_TOTAL_CHARS = 7000  # запас до лимита LIMIT_POSTS в handlers.py
MIN_POST_LEN = 80       # пропускаем слишком короткие сообщения


async def fetch_posts(channel: str, pages: int = 3) -> list[str]:
    """
    Выгружает последние посты из публичного канала.

    channel — юзернейм с @ или без, например '@design' или 'design'.
    pages   — сколько страниц загрузить (каждая ~20 постов).

    Возвращает список текстов, суммарно не превышающих MAX_TOTAL_CHARS.
    """
    username = channel.lstrip("@")
    url = f"https://t.me/s/{username}"

    headers = {"User-Agent": "Mozilla/5.0 (compatible; bot)"}
    posts: list[str] = []
    total_chars = 0

    async with aiohttp.ClientSession(headers=headers) as session:
        # Первая страница
        async with session.get(url) as resp:
            if resp.status != 200:
                raise RuntimeError(
                    f"Канал @{username} недоступен (HTTP {resp.status}).\n"
                    "Проверь: канал существует и является публичным."
                )
            html = await resp.text()

        for page in range(pages):
            soup = BeautifulSoup(html, "html.parser")

            # Собираем тексты постов с текущей страницы
            for tag in soup.find_all("div", class_="tgme_widget_message_text"):
                text = tag.get_text(separator="\n").strip()
                if len(text) < MIN_POST_LEN:
                    continue
                if total_chars + len(text) > MAX_TOTAL_CHARS:
                    return posts
                posts.append(text)
                total_chars += len(text)

            # Следующая страница — ищем ссылку «Load more»
            if page < pages - 1:
                load_more = soup.find("a", class_="tme_messages_more")
                if not load_more:
                    break
                next_url = "https://t.me" + load_more["href"]
                async with session.get(next_url) as resp:
                    if resp.status != 200:
                        break
                    html = await resp.text()

    return posts
