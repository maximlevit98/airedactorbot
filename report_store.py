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


def list_analyzed_channels(user_id: int) -> list:
    """
    Возвращает список каналов у которых есть хотя бы один отчёт.
    Каждый элемент: {"channel": "@name", "analyzed_at": "2026-...", "posts_count": 100}
    """
    d = _user_dir(user_id)
    if not d.exists():
        return []
    # Собираем уникальные слаги из имён файлов вида {slug}_{ts}.json
    slugs: dict[str, Path] = {}
    for p in d.glob("*.json"):
        # Имя файла: slug_YYYYMMDD_HHMMSS.json — slug может содержать _
        # Последние два сегмента после разбиения по _ — дата и время
        parts = p.stem.rsplit("_", 2)
        if len(parts) == 3:
            slug = parts[0]
        else:
            continue
        # Берём самый свежий файл для каждого слага
        if slug not in slugs or p.name > slugs[slug].name:
            slugs[slug] = p

    result = []
    for slug, path in slugs.items():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            channel = data.get("channel") or ("@" + slug)
            analyzed_at = data.get("fetched_at", "")
            posts_count = data.get("total_fetched", data.get("posts_for_analysis", 0))
            result.append({
                "channel": channel,
                "analyzed_at": analyzed_at,
                "posts_count": posts_count,
            })
        except Exception as e:
            logger.warning("Не удалось прочитать %s: %s", path, e)
    return result


def format_analysis_report(report: dict) -> str:
    """Форматирует отчёт об анализе в красивый HTML для Telegram (не более 4000 символов)."""
    channel = report.get("channel", "?")
    fetched_at = report.get("fetched_at", "")
    if fetched_at:
        try:
            from datetime import datetime as _dt
            dt = _dt.fromisoformat(fetched_at)
            date_str = dt.strftime("%d.%m.%Y %H:%M")
        except Exception:
            date_str = fetched_at[:16]
    else:
        date_str = "—"
    total = report.get("total_fetched", report.get("posts_for_analysis", 0))
    analysis = report.get("analysis", {})

    lines = [
        f"📊 <b>Анализ стиля: {channel}</b>",
        f"<i>Дата: {date_str} · Постов: {total}</i>",
        "",
    ]
    if tone := analysis.get("tone"):
        lines.append(f"🎭 <b>Тон:</b> {tone}")
    if avg_len := analysis.get("avg_length"):
        lines.append(f"📏 <b>Длина постов:</b> {avg_len}")
    if emoji := analysis.get("emoji_style"):
        lines.append(f"😊 <b>Эмодзи:</b> {emoji}")
    if structure := analysis.get("structure"):
        lines.append(f"🏗 <b>Структура:</b> {structure}")
    if vocab := analysis.get("vocabulary"):
        vocab_str = ", ".join(vocab[:8]) if isinstance(vocab, list) else str(vocab)
        lines.append(f"📝 <b>Лексика:</b> {vocab_str}")
    if hooks := analysis.get("hooks"):
        lines.append(f"🪝 <b>Хуки:</b> {hooks}")
    if cta := analysis.get("cta"):
        lines.append(f"📢 <b>Призывы к действию:</b> {cta}")
    if topics := analysis.get("topics"):
        topics_str = ", ".join(topics[:6]) if isinstance(topics, list) else str(topics)
        lines.append(f"🏷 <b>Темы:</b> {topics_str}")
    if summary := analysis.get("summary"):
        lines.append(f"\n💬 <i>{summary}</i>")

    if not analysis:
        lines.append("<i>Анализ не найден в отчёте.</i>")

    text = "\n".join(lines)
    # Обрезаем до 4000 символов
    if len(text) > 4000:
        text = text[:3997] + "…"
    return text


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
