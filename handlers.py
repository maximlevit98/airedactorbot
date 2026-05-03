import logging
import os
from aiogram import Router, F, Bot
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery

from claude_client import ClaudeClient
from keyboards import main_menu, post_result_keyboard

logger = logging.getLogger(__name__)
router = Router()
claude = ClaudeClient()


class EditFlow(StatesGroup):
    waiting_for_text = State()


class GenerateFlow(StatesGroup):
    waiting_for_topic = State()


# хранит последний сгенерированный текст и тему/оригинал для retry
LAST_INPUT_KEY = "last_input"
LAST_RESULT_KEY = "last_result"
LAST_MODE_KEY = "last_mode"


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Привет! Я помогу тебе редактировать посты для канала с помощью Claude AI.\n\n"
        "Выбери действие:",
        reply_markup=main_menu(),
    )


@router.callback_query(F.data == "action:edit")
async def cb_action_edit(callback: CallbackQuery, state: FSMContext):
    await state.set_state(EditFlow.waiting_for_text)
    await callback.message.edit_text("Отправь текст поста, который нужно улучшить:")
    await callback.answer()


@router.callback_query(F.data == "action:generate")
async def cb_action_generate(callback: CallbackQuery, state: FSMContext):
    await state.set_state(GenerateFlow.waiting_for_topic)
    await callback.message.edit_text("Введи тему или краткое описание для нового поста:")
    await callback.answer()


@router.message(EditFlow.waiting_for_text)
async def handle_edit_text(message: Message, state: FSMContext):
    thinking_msg = await message.answer("⏳ Редактирую...")
    try:
        result = await claude.edit_post(message.text)
    except Exception as e:
        logger.error("Claude API error: %s", e)
        await thinking_msg.edit_text("Ошибка при обращении к Claude. Попробуй позже.")
        return

    await state.update_data(
        {LAST_INPUT_KEY: message.text, LAST_RESULT_KEY: result, LAST_MODE_KEY: "edit"}
    )
    await state.set_state(None)
    await thinking_msg.delete()
    await message.answer(
        f"📝 <b>Готово:</b>\n\n{result}",
        parse_mode="HTML",
        reply_markup=post_result_keyboard("edit"),
    )


@router.message(GenerateFlow.waiting_for_topic)
async def handle_generate_topic(message: Message, state: FSMContext):
    thinking_msg = await message.answer("⏳ Пишу пост...")
    try:
        result = await claude.generate_post(message.text)
    except Exception as e:
        logger.error("Claude API error: %s", e)
        await thinking_msg.edit_text("Ошибка при обращении к Claude. Попробуй позже.")
        return

    await state.update_data(
        {LAST_INPUT_KEY: message.text, LAST_RESULT_KEY: result, LAST_MODE_KEY: "generate"}
    )
    await state.set_state(None)
    await thinking_msg.delete()
    await message.answer(
        f"📝 <b>Готово:</b>\n\n{result}",
        parse_mode="HTML",
        reply_markup=post_result_keyboard("generate"),
    )


@router.callback_query(F.data == "result:publish")
async def cb_publish(callback: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    result = data.get(LAST_RESULT_KEY)
    channel_id = os.getenv("CHANNEL_ID")

    if not result:
        await callback.answer("Нет текста для публикации.", show_alert=True)
        return

    if not channel_id:
        await callback.answer("CHANNEL_ID не задан в .env", show_alert=True)
        return

    try:
        await bot.send_message(channel_id, result)
        await callback.message.edit_text(
            f"✅ Пост опубликован!\n\n{result}",
            reply_markup=main_menu(),
        )
    except Exception as e:
        logger.error("Failed to publish: %s", e)
        await callback.answer(f"Ошибка публикации: {e}", show_alert=True)

    await callback.answer()


@router.callback_query(F.data.startswith("result:retry:"))
async def cb_retry(callback: CallbackQuery, state: FSMContext):
    mode = callback.data.split(":")[-1]
    data = await state.get_data()
    last_input = data.get(LAST_INPUT_KEY)

    if not last_input:
        await callback.answer("Не найден оригинальный текст.", show_alert=True)
        return

    await callback.answer()
    thinking_msg = await callback.message.answer("⏳ Генерирую новый вариант...")

    try:
        if mode == "edit":
            result = await claude.edit_post(last_input)
        else:
            result = await claude.generate_post(last_input)
    except Exception as e:
        logger.error("Claude API error: %s", e)
        await thinking_msg.edit_text("Ошибка при обращении к Claude. Попробуй позже.")
        return

    await state.update_data({LAST_RESULT_KEY: result})
    await thinking_msg.delete()
    await callback.message.answer(
        f"📝 <b>Новый вариант:</b>\n\n{result}",
        parse_mode="HTML",
        reply_markup=post_result_keyboard(mode),
    )


@router.callback_query(F.data == "result:menu")
async def cb_back_to_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Выбери действие:", reply_markup=main_menu())
    await callback.answer()
