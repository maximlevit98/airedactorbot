"""
Загрузка профиля стиля для пользователя.
Multi-tenant: каждый пользователь имеет свой канал и свой анализ.
"""
from report_store import load_latest_report_any_age
from users_store import get_channel


def format_style_context(profile: dict) -> str:
    """Превращает словарь профиля стиля в текстовый блок для промпта."""
    if not profile or profile.get("error"):
        return ""
    lines = ["--- СТИЛЬ КАНАЛА ---"]
    if tone := profile.get("tone"):
        lines.append(f"Тон: {tone}")
    if avg_len := profile.get("avg_length"):
        lines.append(f"Длина постов: {avg_len}")
    if emoji := profile.get("emoji_style"):
        lines.append(f"Эмодзи: {emoji}")
    if structure := profile.get("structure"):
        lines.append(f"Структура: {structure}")
    if vocab := profile.get("vocabulary"):
        lines.append(f"Лексика: {', '.join(vocab[:8])}")
    if hooks := profile.get("hooks"):
        lines.append(f"Хуки (начало постов): {hooks}")
    if cta := profile.get("cta"):
        lines.append(f"Финал/CTA: {cta}")
    if summary := profile.get("summary"):
        lines.append(f"Голос: {summary}")
    if topics := profile.get("topics"):
        t = topics if isinstance(topics, str) else ", ".join(topics[:6])
        lines.append(f"Основные темы: {t}")
    lines.append("--- КОНЕЦ СТИЛЯ ---")
    return "\n".join(lines)


def load_style_for_user(user_id: int) -> str:
    """Загружает стиль по user_id → его каналу → последнему отчёту."""
    channel = get_channel(user_id)
    if not channel:
        return ""
    report = load_latest_report_any_age(channel, user_id)
    if not report:
        return ""
    return format_style_context(report.get("analysis", {}))


def load_style_for_channel(channel: str = "", user_id: int = 0) -> str:
    """
    Универсальная загрузка стиля.
    Если передан user_id — грузим именно по нему (новый путь).
    Иначе — ищем в старом reports/{channel}_*.json (legacy).
    """
    if user_id:
        return load_style_for_user(user_id)
    if not channel:
        return ""
    # Legacy: ищем в корневом reports/ без user_id
    from pathlib import Path
    import json
    old_dir = Path("reports")
    slug = channel.lstrip("@").lower()
    if old_dir.exists():
        candidates = sorted(
            [p for p in old_dir.glob(f"{slug}_*.json") if p.is_file()],
            reverse=True,
        )
        if candidates:
            try:
                data = json.loads(candidates[0].read_text(encoding="utf-8"))
                return format_style_context(data.get("analysis", {}))
            except Exception:
                pass
    return ""


def style_hint(style: str) -> str:
    """Подсказка пользователю если анализ стиля не найден."""
    if style:
        return ""
    return (
        "\n\n<i>💡 Добавь свой канал через ⚙️ Настройки → 📡 Мой канал "
        "чтобы посты писались в твоём стиле.</i>"
    )
