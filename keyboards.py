from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✍️ Написать пост", callback_data="action:new_post"),
        InlineKeyboardButton(text="📂 Черновики", callback_data="action:drafts"),
    )
    builder.row(
        InlineKeyboardButton(text="📬 Готовые посты", callback_data="action:ready_posts"),
        InlineKeyboardButton(text="⚙️ Настройки", callback_data="action:settings"),
    )
    builder.row(
        InlineKeyboardButton(text="💡 Идеи", callback_data="action:ideas"),
        InlineKeyboardButton(text="📋 План", callback_data="action:plan"),
    )
    builder.row(
        InlineKeyboardButton(text="✏️ Редактура", callback_data="action:edit"),
        InlineKeyboardButton(text="📰 Дайджест", callback_data="action:digest"),
    )
    builder.row(
        InlineKeyboardButton(text="🎨 Анализ стиля", callback_data="action:style"),
        InlineKeyboardButton(text="💳 Пополнить", callback_data="action:buy"),
    )
    return builder.as_markup()


def cancel_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="❌ Отмена", callback_data="action:cancel"),
    )
    return builder.as_markup()


def ideas_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🔄 Ещё идеи", callback_data="action:retry_ideas"),
        InlineKeyboardButton(text="✍️ Написать пост", callback_data="action:new_post"),
    )
    builder.row(
        InlineKeyboardButton(text="◀️ В меню", callback_data="action:menu"),
    )
    return builder.as_markup()


def plan_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🔄 Другой план", callback_data="action:retry_plan"),
        InlineKeyboardButton(text="✏️ Писать черновик", callback_data="action:edit"),
    )
    builder.row(
        InlineKeyboardButton(text="◀️ В меню", callback_data="action:menu"),
    )
    return builder.as_markup()


def edit_result_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🔄 Ещё вариант", callback_data="action:retry_edit"),
        InlineKeyboardButton(text="✏️ Другая инструкция", callback_data="action:edit_again"),
    )
    builder.row(
        InlineKeyboardButton(text="◀️ В меню", callback_data="action:menu"),
    )
    return builder.as_markup()


def digest_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🔄 Ещё раз", callback_data="action:retry_digest"),
        InlineKeyboardButton(text="💡 Идеи на основе", callback_data="action:ideas"),
    )
    builder.row(
        InlineKeyboardButton(text="◀️ В меню", callback_data="action:menu"),
    )
    return builder.as_markup()


def pool_progress_keyboard(pool_idx: int, total_pools: int) -> InlineKeyboardMarkup:
    """Клавиатура после анализа очередного пула."""
    builder = InlineKeyboardBuilder()
    if pool_idx < total_pools - 1:
        builder.row(
            InlineKeyboardButton(
                text=f"▶️ Следующий пул ({pool_idx + 2}/{total_pools})",
                callback_data="fetch:next_pool",
            )
        )
    else:
        builder.row(
            InlineKeyboardButton(text="✅ Объединить всё", callback_data="fetch:merge"),
        )
    builder.row(
        InlineKeyboardButton(text="◀️ В меню", callback_data="action:menu"),
    )
    return builder.as_markup()


def fetch_cache_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Использовать кэш", callback_data="fetch:use_cache"),
        InlineKeyboardButton(text="🔄 Обновить", callback_data="fetch:refresh"),
    )
    builder.row(
        InlineKeyboardButton(text="◀️ В меню", callback_data="action:menu"),
    )
    return builder.as_markup()


# ── POST FLOW ─────────────────────────────────────────────────────────────────

def post_hook_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🔄 Другие хуки", callback_data="post:retry_hooks"),
        InlineKeyboardButton(text="⏭ Пропустить", callback_data="post:skip_hook"),
    )
    builder.row(
        InlineKeyboardButton(text="◀️ В меню", callback_data="action:menu"),
    )
    return builder.as_markup()


def post_plan_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Писать черновик", callback_data="post:write_draft"),
        InlineKeyboardButton(text="✏️ Изменить план", callback_data="post:edit_plan"),
    )
    builder.row(
        InlineKeyboardButton(text="🔄 Другой план", callback_data="post:retry_plan"),
        InlineKeyboardButton(text="◀️ В меню", callback_data="action:menu"),
    )
    return builder.as_markup()


def post_draft_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Готово", callback_data="post:done"),
        InlineKeyboardButton(text="✏️ Доработать", callback_data="post:edit_draft"),
    )
    builder.row(
        InlineKeyboardButton(text="🔄 Переписать", callback_data="post:retry_draft"),
        InlineKeyboardButton(text="◀️ В меню", callback_data="action:menu"),
    )
    return builder.as_markup()


# ── DRAFTS ────────────────────────────────────────────────────────────────────

def drafts_list_keyboard(drafts: list[dict]) -> InlineKeyboardMarkup:
    """Список черновиков — каждый как отдельная кнопка."""
    builder = InlineKeyboardBuilder()
    for d in drafts[:8]:  # не больше 8 в списке
        topic = d.get("topic", "Без темы")
        preview = (topic[:28] + "…") if len(topic) > 28 else topic
        label = d.get("stage_label", "")
        builder.row(
            InlineKeyboardButton(
                text=f"📄 {preview} · {label}",
                callback_data=f"draft:open:{d['draft_id']}",
            )
        )
    builder.row(
        InlineKeyboardButton(text="◀️ В меню", callback_data="action:menu"),
    )
    return builder.as_markup()


def draft_item_keyboard(draft_id: str) -> InlineKeyboardMarkup:
    """Кнопки для конкретного черновика."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="▶️ Продолжить", callback_data=f"draft:resume:{draft_id}"),
        InlineKeyboardButton(text="🗑 Удалить", callback_data=f"draft:delete:{draft_id}"),
    )
    builder.row(
        InlineKeyboardButton(text="◀️ К черновикам", callback_data="action:drafts"),
    )
    return builder.as_markup()


def style_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✏️ Редактировать пост", callback_data="action:edit"),
        InlineKeyboardButton(text="◀️ В меню", callback_data="action:menu"),
    )
    return builder.as_markup()


# ── READY POSTS ───────────────────────────────────────────────────────────────

def ready_posts_list_keyboard(posts: list[dict]) -> InlineKeyboardMarkup:
    """Список готовых постов — каждый как отдельная кнопка."""
    builder = InlineKeyboardBuilder()
    for p in posts[:10]:  # не больше 10 в списке
        topic = p.get("topic", "Без темы")
        preview = (topic[:30] + "…") if len(topic) > 30 else topic
        from datetime import datetime
        dt = datetime.fromisoformat(p["saved_at"]).strftime("%d.%m")
        builder.row(
            InlineKeyboardButton(
                text=f"📄 {preview} · {dt}",
                callback_data=f"rpost:open:{p['post_id']}",
            )
        )
    builder.row(
        InlineKeyboardButton(text="◀️ В меню", callback_data="action:menu"),
    )
    return builder.as_markup()


def ready_post_item_keyboard(post_id: str) -> InlineKeyboardMarkup:
    """Кнопки для конкретного готового поста."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🗑 Удалить", callback_data=f"rpost:delete:{post_id}"),
        InlineKeyboardButton(text="◀️ К списку", callback_data="action:ready_posts"),
    )
    return builder.as_markup()


# ── SETTINGS ──────────────────────────────────────────────────────────────────

def _bar(value: int, width: int = 10) -> str:
    """Прогресс-бар через юникод-блоки."""
    filled = round(value / (100 / width))
    filled = max(0, min(width, filled))
    return "▓" * filled + "░" * (width - filled)


def settings_main_keyboard(settings: dict) -> InlineKeyboardMarkup:
    """Главный экран настроек — список параметров с прогресс-барами."""
    from settings_store import PARAM_ORDER, PARAM_LABELS, LENGTH_LABELS
    builder = InlineKeyboardBuilder()
    for key in PARAM_ORDER:
        v = int(settings.get(key, 0))
        label = PARAM_LABELS[key]
        builder.row(
            InlineKeyboardButton(
                text=f"{label}: {_bar(v)} {v}%",
                callback_data=f"set:param:{key}",
            )
        )
    length = settings.get("length", "medium")
    builder.row(
        InlineKeyboardButton(
            text=f"📏 Длина: {LENGTH_LABELS.get(length, length)}",
            callback_data="set:param:length",
        )
    )
    builder.row(
        InlineKeyboardButton(text="📡 Мой канал", callback_data="set:channel"),
    )
    builder.row(
        InlineKeyboardButton(text="🔄 Сбросить", callback_data="set:reset"),
        InlineKeyboardButton(text="◀️ В меню", callback_data="action:menu"),
    )
    return builder.as_markup()


def settings_param_keyboard(param: str, value: int) -> InlineKeyboardMarkup:
    """Экран регулировки одного параметра."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="−10", callback_data=f"set:adj:{param}:-10"),
        InlineKeyboardButton(text="−5",  callback_data=f"set:adj:{param}:-5"),
        InlineKeyboardButton(text="+5",  callback_data=f"set:adj:{param}:5"),
        InlineKeyboardButton(text="+10", callback_data=f"set:adj:{param}:10"),
    )
    builder.row(
        InlineKeyboardButton(text="0",   callback_data=f"set:val:{param}:0"),
        InlineKeyboardButton(text="25",  callback_data=f"set:val:{param}:25"),
        InlineKeyboardButton(text="50",  callback_data=f"set:val:{param}:50"),
        InlineKeyboardButton(text="75",  callback_data=f"set:val:{param}:75"),
        InlineKeyboardButton(text="100", callback_data=f"set:val:{param}:100"),
    )
    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="set:back"),
    )
    return builder.as_markup()


def settings_length_keyboard(current: str) -> InlineKeyboardMarkup:
    """Экран выбора длины поста."""
    from settings_store import LENGTH_LABELS
    builder = InlineKeyboardBuilder()
    for key, label in LENGTH_LABELS.items():
        marker = "✅ " if key == current else ""
        builder.row(
            InlineKeyboardButton(
                text=f"{marker}{label}",
                callback_data=f"set:len:{key}",
            )
        )
    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="set:back"),
    )
    return builder.as_markup()
