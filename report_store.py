"""
Хранение отчётов об анализе стиля канала.
Файлы: reports/{user_id}/{channel}_{datetime}.json
"""
import hashlib
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

from storage import BASE
REPORTS_DIR = BASE / "reports"
CACHE_TTL_DAYS = 7       # кэш считается свежим 7 дней
MAX_POSTS_FOR_ANALYSIS = 100  # бесплатный лимит анализа


def _channel_slug(channel: str) -> str:
    return channel.lstrip("@").lower()


def _user_dir(user_id: int) -> Path:
    return REPORTS_DIR / str(user_id)


def post_hash(post: str) -> str:
    """MD5-хэш текста поста для быстрого сравнения."""
    return hashlib.md5(post.encode("utf-8")).hexdigest()


def _latest_report_path(channel: str, user_id: int) -> Optional[Path]:
    """Путь к последнему файлу отчёта пользователя (без проверки TTL)."""
    d = _user_dir(user_id)
    if not d.exists():
        return None
    slug = _channel_slug(channel)
    candidates = sorted(d.glob(f"{slug}_*.json"), reverse=True)
    return candidates[0] if candidates else None


def get_analyzed_hashes(channel: str, user_id: int) -> set[str]:
    """Возвращает хэши уже проанализированных постов пользователя."""
    path = _latest_report_path(channel, user_id)
    if not path:
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        posts = data.get("all_posts") or data.get("posts", [])
        return {post_hash(p) for p in posts}
    except Exception as e:
        logger.warning("Не удалось загрузить хэши из %s: %s", path, e)
        return set()


def load_latest_report_any_age(channel: str, user_id: int) -> Optional[dict]:
    """Загружает последний отчёт пользователя без проверки TTL."""
    path = _latest_report_path(channel, user_id)
    if not path:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("Не удалось загрузить отчёт %s: %s", path, e)
        return None


def save_report(
    channel: str,
    posts: list[str],
    total: int,
    analysis: dict,
    user_id: int,
    all_posts: Optional[list[str]] = None,
    pool_analyses: Optional[list[dict]] = None,
) -> Path:
    """Сохраняет отчёт в JSON. Возвращает путь к файлу."""
    d = _user_dir(user_id)
    d.mkdir(parents=True, exist_ok=True)
    slug = _channel_slug(channel)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = d / f"{slug}_{ts}.json"
    data = {
        "channel": channel,
        "user_id": user_id,
        "fetched_at": datetime.now().isoformat(),
        "total_fetched": total,
        "posts_for_analysis": len(posts),
        "posts": posts,
        "all_posts": all_posts or posts,
        "pool_analyses": pool_analyses or [],
        "analysis": analysis,
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Отчёт сохранён: %s", path)
    return path


def load_latest_report(channel: str, user_id: int) -> Optional[dict]:
    """
    Загружает последний отчёт по каналу и пользователю.
    Возвращает None если нет или старше CACHE_TTL_DAYS.
    """
    path = _latest_report_path(channel, user_id)
    if not path:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        fetched_at = datetime.fromisoformat(data["fetched_at"])
        if datetime.now() - fetched_at > timedelta(days=CACHE_TTL_DAYS):
            return None
        return data
    except Exception as e:
        logger.warning("Не удалось загрузить отчёт %s: %s", path, e)
        return None
