"""
Оплата: Telegram Stars и ЮКасса (рубли).
Пакеты кредитов: starter / basic / pro.
"""
from aiogram.types import LabeledPrice, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from users_store import PACKAGES


def buy_keyboard() -> InlineKeyboardMarkup:
    """Выбор способа оплаты."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⭐ Telegram Stars", callback_data="buy:method:stars"),
        InlineKeyboardButton(text="💳 Картой (ЮКасса)", callback_data="buy:method:rub"),
    )
    builder.row(
        InlineKeyboardButton(text="◀️ В меню", callback_data="action:menu"),
    )
    return builder.as_markup()


def buy_stars_keyboard() -> InlineKeyboardMarkup:
    """Пакеты за Stars."""
    builder = InlineKeyboardBuilder()
    for pkg_id, pkg in PACKAGES.items():
        builder.row(
            InlineKeyboardButton(
                text=f"⭐ {pkg['label']} — {pkg['stars']} Stars",
                callback_data=f"buy:stars:{pkg_id}",
            )
        )
    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="action:buy"),
    )
    return builder.as_markup()


def buy_rub_keyboard() -> InlineKeyboardMarkup:
    """Пакеты за рубли."""
    builder = InlineKeyboardBuilder()
    for pkg_id, pkg in PACKAGES.items():
        builder.row(
            InlineKeyboardButton(
                text=f"💳 {pkg['label']} — {pkg['rub']} ₽",
                callback_data=f"buy:rub:{pkg_id}",
            )
        )
    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="action:buy"),
    )
    return builder.as_markup()


def no_credits_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура когда кончились кредиты."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⭐ Telegram Stars", callback_data="buy:method:stars"),
        InlineKeyboardButton(text="💳 Картой (ЮКасса)", callback_data="buy:method:rub"),
    )
    builder.row(
        InlineKeyboardButton(text="◀️ В меню", callback_data="action:menu"),
    )
    return builder.as_markup()


def make_stars_prices(pkg_id: str) -> list[LabeledPrice]:
    pkg = PACKAGES[pkg_id]
    return [LabeledPrice(label=pkg["label"], amount=pkg["stars"])]


def make_rub_prices(pkg_id: str) -> list[LabeledPrice]:
    pkg = PACKAGES[pkg_id]
    return [LabeledPrice(label=pkg["label"], amount=pkg["rub"] * 100)]  # в копейках


# Обратная совместимость
def make_invoice_prices(pkg_id: str) -> list[LabeledPrice]:
    return make_stars_prices(pkg_id)
