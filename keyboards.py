from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✏️ Редактировать пост", callback_data="action:edit"),
        InlineKeyboardButton(text="✨ Написать пост", callback_data="action:generate"),
    )
    return builder.as_markup()


def post_result_keyboard(mode: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📢 Опубликовать", callback_data="result:publish"),
        InlineKeyboardButton(text="🔄 Переделать", callback_data=f"result:retry:{mode}"),
    )
    builder.row(
        InlineKeyboardButton(text="◀️ В меню", callback_data="result:menu"),
    )
    return builder.as_markup()
