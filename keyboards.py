from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
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
        InlineKeyboardButton(text="📋 Запланировать", callback_data="action:plan"),
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


def style_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✏️ Редактировать пост", callback_data="action:edit"),
        InlineKeyboardButton(text="◀️ В меню", callback_data="action:menu"),
    )
    return builder.as_markup()
