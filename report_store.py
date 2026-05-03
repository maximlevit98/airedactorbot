"""
Хранение отчётов об анализе стиля канала.
Файлы: reports/{channel}_{datetime}.json
"""
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

REPORTS_DIR = Path("reports")
CACHE_TTL_DAYS = 7  # кэш считается свежим 7 дней


def _channel_slug(channel: str) -> str:
    return channel.lstrip("@").lower()


def save_report(
    channel: str,
    posts: list[str],
    total: int,
    analysis: dict,
    all_posts: Optional[list[str]] = None,
    pool_analyses: Optional[list[dict]] = None,
) -> Path:
    """Сохраняет отчёт в JSON. Возвращает путь к файлу."""
    REPORTS_DIR.mkdir(exist_ok=True)
    slug = _channel_slug(channel)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = REPORTS_DIR / f"{slug}_{ts}.json"
    data = {
        "channel": channel,
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


def load_latest_report(channel: str) -> Optional[dict]:
    """
    Загружает последний отчёт по каналу.
    Возвращает None если отчёта нет или он старше CACHE_TTL_DAYS.
    """
    if not REPORTS_DIR.exists():
        return None
    slug = _channel_slug(channel)
    candidates = sorted(REPORTS_DIR.glob(f"{slug}_*.json"), reverse=True)
    if not candidates:
        return None
    latest = candidates[0]
    try:
        data = json.loads(latest.read_text(encoding="utf-8"))
        fetched_at = datetime.fromisoformat(data["fetched_at"])
        if datetime.now() - fetched_at > timedelta(days=CACHE_TTL_DAYS):
            return None  # устарел
        return data
    except Exception as e:
        logger.warning("Не удалось загрузить отчёт %s: %s", latest, e)
        return None


def list_reports(channel: str) -> list[dict]:
    """Список всех отчётов по каналу (от новых к старым)."""
    if not REPORTS_DIR.exists():
        return []
    slug = _channel_slug(channel)
    result = []
    for path in sorted(REPORTS_DIR.glob(f"{slug}_*.json"), reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            result.append({
                "path": str(path),
                "fetched_at": data.get("fetched_at"),
                "total_fetched": data.get("total_fetched"),
                "posts_for_analysis": data.get("posts_for_analysis"),
            })
        except Exception:
            pass
    return result
