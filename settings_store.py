"""
Хранение настроек тона поста (per-user) — ползунки 0-100.
Файлы: settings/{user_id}.json
"""
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

from storage import BASE
SETTINGS_DIR = BASE / "settings"

# Базовые значения если ничего не нашли
HARDCODED_DEFAULTS = {
    "sources": 30,
    "formality": 25,
    "friendliness": 75,
    "emoji": 35,
    "personal": 70,
    "concrete": 80,
    "engagement": 60,
    "length": "medium",  # short | medium | long
}

PARAM_LABELS = {
    "sources":     "🔗 Источники",
    "formality":   "📐 Формальность",
    "friendliness": "🤝 Дружелюбие",
    "emoji":       "😊 Эмодзи",
    "personal":    "💭 Личный опыт",
    "concrete":    "🎯 Конкретика",
    "engagement":  "❓ Вовлечение",
}

PARAM_ORDER = list(PARAM_LABELS.keys())

LENGTH_LABELS = {
    "short":  "Короткий (200–400)",
    "medium": "Средний (500–900)",
    "long":   "Длинный (1000–1500)",
}


def _path(user_id: int) -> Path:
    return SETTINGS_DIR / f"{user_id}.json"


def _defaults_from_style(channel: str = "") -> dict:
    """Извлекает разумные дефолты из последнего анализа стиля."""
    try:
        from report_store import load_latest_report_any_age
    except Exception:
        return HARDCODED_DEFAULTS.copy()

    ch = channel.strip() if channel else ""
    if not ch:
        return HARDCODED_DEFAULTS.copy()

    report = load_latest_report_any_age(ch)
    if not report:
        return HARDCODED_DEFAULTS.copy()

    a = report.get("analysis", {}) or {}
    result = HARDCODED_DEFAULTS.copy()

    tone = (a.get("tone") or "").lower()
    if any(w in tone for w in ("разговор", "лирич", "неформ", "личн")):
        result["formality"] = 20
        result["friendliness"] = 80
    elif any(w in tone for w in ("професс", "формал", "деловой")):
        result["formality"] = 65
        result["friendliness"] = 45

    emoji = (a.get("emoji_style") or "").lower()
    if "отсутств" in emoji:
        result["emoji"] = 0
    elif "редко" in emoji:
        result["emoji"] = 20
    elif "умерен" in emoji:
        result["emoji"] = 45
    elif "часто" in emoji:
        result["emoji"] = 75

    avg_len = (a.get("avg_length") or "").lower()
    if "коротк" in avg_len:
        result["length"] = "short"
    elif "длинн" in avg_len:
        result["length"] = "long"
    else:
        result["length"] = "medium"

    return result


def load_settings(user_id: int) -> dict:
    """Загружает настройки пользователя. При первом обращении инициализирует из стиля."""
    path = _path(user_id)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            # Дополняем недостающие ключи дефолтами (на случай миграций)
            for k, v in HARDCODED_DEFAULTS.items():
                data.setdefault(k, v)
            return data
        except Exception as e:
            logger.warning("Не удалось прочитать настройки %s: %s", path, e)
    # Первый раз — берём из анализа стиля
    defaults = _defaults_from_style()
    save_settings(user_id, defaults)
    return defaults


def save_settings(user_id: int, settings: dict) -> None:
    SETTINGS_DIR.mkdir(exist_ok=True)
    _path(user_id).write_text(
        json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def update_param(user_id: int, param: str, value) -> dict:
    """Обновляет один параметр и сохраняет. Возвращает обновлённые настройки."""
    settings = load_settings(user_id)
    if param in PARAM_LABELS:
        # Числовой параметр 0-100
        try:
            v = int(value)
        except (ValueError, TypeError):
            return settings
        settings[param] = max(0, min(100, v))
    elif param == "length":
        if value in LENGTH_LABELS:
            settings["length"] = value
    save_settings(user_id, settings)
    return settings


def reset_settings(user_id: int) -> dict:
    """Сбрасывает к дефолтам из анализа стиля."""
    defaults = _defaults_from_style()
    save_settings(user_id, defaults)
    return defaults
