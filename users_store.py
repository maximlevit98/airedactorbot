"""
Профили пользователей: канал, кредиты, статистика токенов.
Файлы: users/{user_id}.json
"""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

from storage import BASE
USERS_DIR = BASE / "users"

# Кредитная система
CREDITS_NEW_POST      = 5   # новый PostFlow
CREDITS_IDEAS         = 1   # генерация идей
CREDITS_PLAN          = 2   # standalone план
CREDITS_EDIT          = 2   # standalone редактура
CREDITS_QUICK_POST    = 5   # быстрый пост
CREDITS_DIGEST        = 1   # дайджест

# Стоимость модели в $ за 1M токенов (для логирования реальных затрат)
MODEL_COST = {
    "claude-opus-4-6":        {"in": 15.0, "out": 75.0},
    "claude-sonnet-4-6":      {"in":  3.0, "out": 15.0},
    "claude-haiku-4-5-20251001": {"in": 1.0, "out":  5.0},
}

# Пакеты Stars → кредиты
PACKAGES = {
    "starter": {"credits": 50,  "stars": 130, "rub": 149,  "label": "50 кредитов (~10 постов)"},
    "basic":   {"credits": 200, "stars": 450, "rub": 499,  "label": "200 кредитов (~40 постов)"},
    "pro":     {"credits": 600, "stars": 1200, "rub": 1290, "label": "600 кредитов (~120 постов)"},
}


def _path(user_id: int) -> Path:
    return USERS_DIR / f"{user_id}.json"


def _default_profile(user_id: int) -> dict:
    return {
        "user_id": user_id,
        "joined_at": datetime.now().isoformat(),
        "channel": "",            # @username канала (основной, для обратной совместимости)
        "channels": [],           # список всех каналов пользователя
        "credits": 0,             # текущий баланс
        "free_post_used": False,  # использован ли бесплатный первый пост
        "total_posts": 0,         # всего завершённых постов
        "total_tokens_in": 0,
        "total_tokens_out": 0,
        "total_cost_usd": 0.0,    # реальная стоимость API
        "total_paid_usd": 0.0,    # сколько заплатил
    }


def get_user(user_id: int) -> dict:
    """Возвращает профиль. Создаёт при первом обращении."""
    USERS_DIR.mkdir(exist_ok=True)
    path = _path(user_id)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            # Дополняем недостающие поля (миграции)
            for k, v in _default_profile(user_id).items():
                data.setdefault(k, v)
            return data
        except Exception as e:
            logger.warning("Ошибка чтения профиля %s: %s", path, e)
    profile = _default_profile(user_id)
    _save(user_id, profile)
    return profile


def _save(user_id: int, profile: dict) -> None:
    USERS_DIR.mkdir(exist_ok=True)
    _path(user_id).write_text(
        json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def set_channel(user_id: int, channel: str) -> None:
    """Сохраняет канал пользователя (основной, для обратной совместимости)."""
    profile = get_user(user_id)
    profile["channel"] = channel.strip()
    _save(user_id, profile)


def get_channel(user_id: int) -> str:
    """Возвращает канал пользователя или ''."""
    return get_user(user_id).get("channel", "")


def add_channel(user_id: int, channel: str) -> list:
    """Добавляет канал в список если его нет. Возвращает актуальный список."""
    channel = channel.strip()
    if not channel.startswith("@"):
        channel = "@" + channel
    profile = get_user(user_id)
    channels: list = profile.get("channels", [])
    if channel not in channels:
        channels.append(channel)
        profile["channels"] = channels
        _save(user_id, profile)
    return channels


def remove_channel(user_id: int, channel: str) -> list:
    """Удаляет канал из списка. Возвращает актуальный список."""
    channel = channel.strip()
    if not channel.startswith("@"):
        channel = "@" + channel
    profile = get_user(user_id)
    channels: list = profile.get("channels", [])
    channels = [c for c in channels if c != channel]
    profile["channels"] = channels
    # Если удалили основной канал — сбрасываем его тоже
    if profile.get("channel") == channel:
        profile["channel"] = channels[0] if channels else ""
    _save(user_id, profile)
    return channels


def get_channels(user_id: int) -> list:
    """Возвращает список каналов пользователя."""
    profile = get_user(user_id)
    channels: list = profile.get("channels", [])
    # Миграция: если список пуст но есть одиночный канал — добавляем его
    legacy = profile.get("channel", "")
    if not channels and legacy:
        channels = [legacy]
        profile["channels"] = channels
        _save(user_id, profile)
    return channels


# ── КРЕДИТЫ ──────────────────────────────────────────────────────────────────

def get_balance(user_id: int) -> int:
    return get_user(user_id).get("credits", 0)


def is_first_post_free(user_id: int) -> bool:
    return not get_user(user_id).get("free_post_used", False)


def mark_first_post_used(user_id: int) -> None:
    profile = get_user(user_id)
    profile["free_post_used"] = True
    _save(user_id, profile)


def mark_post_completed(user_id: int) -> None:
    profile = get_user(user_id)
    profile["total_posts"] = profile.get("total_posts", 0) + 1
    _save(user_id, profile)


def add_credits(user_id: int, amount: int, paid_usd: float = 0.0) -> int:
    """Пополняет баланс. Возвращает новый баланс."""
    profile = get_user(user_id)
    profile["credits"] = profile.get("credits", 0) + amount
    profile["total_paid_usd"] = profile.get("total_paid_usd", 0.0) + paid_usd
    _save(user_id, profile)
    logger.info("Пополнение: user=%s +%d кредитов (paid=$%.2f)", user_id, amount, paid_usd)
    return profile["credits"]


def deduct_credits(user_id: int, amount: int) -> bool:
    """
    Списывает кредиты. Возвращает True если успешно, False если не хватает.
    """
    profile = get_user(user_id)
    balance = profile.get("credits", 0)
    if balance < amount:
        return False
    profile["credits"] = balance - amount
    _save(user_id, profile)
    return True


# ── ТОКЕНЫ ───────────────────────────────────────────────────────────────────

def track_usage(user_id: int, tokens_in: int, tokens_out: int, model: str) -> float:
    """
    Логирует реальные затраты токенов. Возвращает стоимость вызова в $.
    """
    rates = MODEL_COST.get(model, {"in": 3.0, "out": 15.0})
    cost = (tokens_in * rates["in"] + tokens_out * rates["out"]) / 1_000_000

    profile = get_user(user_id)
    profile["total_tokens_in"]  = profile.get("total_tokens_in", 0) + tokens_in
    profile["total_tokens_out"] = profile.get("total_tokens_out", 0) + tokens_out
    profile["total_cost_usd"]   = round(profile.get("total_cost_usd", 0.0) + cost, 6)
    _save(user_id, profile)
    return cost


# ── ADMIN ─────────────────────────────────────────────────────────────────────

def all_users() -> list[dict]:
    """Список всех профилей (для /admin_stats)."""
    if not USERS_DIR.exists():
        return []
    result = []
    for path in USERS_DIR.glob("*.json"):
        try:
            result.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            pass
    return result
