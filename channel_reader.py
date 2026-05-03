"""
Чтение постов из публичного Telegram-канала через веб-превью t.me/s/.
Не требует API_ID, API_HASH или авторизации.
"""
import logging

import aiohttp
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

MIN_POST_LEN = 80       # пропускаем слишком короткие сообщения
MAX_ANALYSIS_CHARS = 25000  # лимит для передачи в Claude


async def fetch_all_posts(channel: str, max_pages: int = 30) -> tuple[list[str], int]:
    """
    Выгружает все посты из публичного канала постранично.

    Возвращает (все_посты, всего_найдено).
    Пагинация через ?before=ID — идём от новых к старым.
    """
    username = channel.lstrip("@")
    url = f"https://t.me/s/{username}"
    headers = {"User-Agent": "Mozilla/5.0 (compatible; tg-editor-bot)"}
    all_posts: list[str] = []

    async with aiohttp.ClientSession(headers=headers) as session:
        for page_num in range(max_pages):
            async with session.get(url) as resp:
                if resp.status != 200:
                    if page_num == 0:
                        raise RuntimeError(
                            f"Канал @{username} недоступен (HTTP {resp.status}).\n"
                            "Проверь: канал существует и является публичным."
                        )
                    break
                html = await resp.text()

            soup = BeautifulSoup(html, "html.parser")

            # Собираем тексты постов
            page_posts: list[str] = []
            for tag in soup.find_all("div", class_="tgme_widget_message_text"):
                text = tag.get_text(separator="\n").strip()
                if len(text) >= MIN_POST_LEN:
                    page_posts.append(text)

            if not page_posts:
                break

            all_posts.extend(page_posts)

            # Ищем ссылку на следующую (более старую) страницу
            load_more = soup.find("a", class_="tme_messages_more")
            if not load_more or not load_more.get("href"):
                break  # достигли конца канала
            url = "https://t.me" + load_more["href"]

    total = len(all_posts)
    return all_posts, total


def select_for_analysis(posts: list[str], max_chars: int = MAX_ANALYSIS_CHARS) -> list[str]:
    """Берёт первые (самые новые) посты суммарно не более max_chars символов."""
    selected: list[str] = []
    chars = 0
    for post in posts:
        if chars + len(post) > max_chars:
            break
        selected.append(post)
        chars += len(post)
    return selected
