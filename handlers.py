import logging
from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery

from claude_client import ClaudeEditor
from keyboards import (
    main_menu, cancel_keyboard, ideas_keyboard,
    plan_keyboard, edit_result_keyboard, digest_keyboard, style_keyboard,
)

logger = logging.getLogger(__name__)
router = Router()
claude = ClaudeEditor()


class IdeasFlow(StatesGroup):
    waiting_for_context = State()


class PlanFlow(StatesGroup):
    waiting_for_topic = State()


class EditFlow(StatesGroup):
    waiting_for_draft = State()
    waiting_for_instructions = State()


class DigestFlow(StatesGroup):
    waiting_for_posts = State()


class StyleFlow(StatesGroup):
    waiting_for_posts = State()


def _format_style(profile: dict) -> str:
    if profile.get("error"):
        return f"Анализ получен, но не удалось распарсить JSON:\n\n{profile.get('raw', '')}"
    lines = ["<b>🎨 Профиль стиля канала</b>\n"]
    if tone := profile.get("tone"):
        lines.append(f"<b>Тон:</b> {tone}")
    if topics := profile.get("topics"):
        lines.append(f"<b>Темы:</b> {', '.join(topics)}")
    if avg_len := profile.get("avg_length"):
        lines.append(f"<b>Длина постов:</b> {avg_len}")
    if emoji := profile.get("emoji_style"):
        lines.append(f"<b>Эмодзи:</b> {emoji}")
    if structure := profile.get("structure"):
        lines.append(f"<b>Структура:</b> {structure}")
    if vocab := profile.get("vocabulary"):
        lines.append(f"<b>Лексика:</b> {', '.join(vocab[:8])}")
    if hooks := profile.get("hooks"):
        lines.append(f"<b>Хуки:</b> {hooks}")
    if cta := profile.get("cta"):
        lines.append(f"<b>Призывы к действию:</b> {cta}")
    if summary := profile.get("summary"):
        lines.append(f"\n{summary}")
    return "\n".join(lines)


# ── /start ───────────────────────────────────────────────────────────────────

@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Привет! Я твой редактор Telegram-канала.\n\nВыбери действие:",
        reply_markup=main_menu(),
    )


# ── /cancel / action:cancel ───────────────────────────────────────────────────

@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Отменено. Выбери действие:", reply_markup=main_menu())


@router.callback_query(F.data == "action:cancel")
async def cb_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Отменено. Выбери действие:", reply_markup=main_menu())
    await callback.answer()


# ── action:menu ───────────────────────────────────────────────────────────────

@router.callback_query(F.data == "action:menu")
async def cb_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Выбери действие:", reply_markup=main_menu())
    await callback.answer()


# ── IDEAS ─────────────────────────────────────────────────────────────────────

@router.message(Command("ideas"))
async def cmd_ideas(message: Message, state: FSMContext):
    await state.set_state(IdeasFlow.waiting_for_context)
    await message.answer(
        "Расскажи, что сейчас происходит или что тебя занимает — придумаю идеи для постов:",
        reply_markup=cancel_keyboard(),
    )


@router.callback_query(F.data == "action:ideas")
async def cb_ideas(callback: CallbackQuery, state: FSMContext):
    await state.set_state(IdeasFlow.waiting_for_context)
    await callback.message.edit_text(
        "Расскажи, что сейчас происходит или что тебя занимает — придумаю идеи для постов:",
        reply_markup=cancel_keyboard(),
    )
    await callback.answer()


@router.message(IdeasFlow.waiting_for_context)
async def handle_ideas_context(message: Message, state: FSMContext):
    await state.update_data(ideas_context=message.text)
    thinking = await message.answer("⏳ Генерирую идеи...")
    try:
        result = await claude.generate_ideas(message.text)
    except Exception as e:
        logger.error("Claude error: %s", e)
        await thinking.edit_text("Ошибка при обращении к Claude. Попробуй позже.")
        return
    await state.set_state(None)
    await thinking.delete()
    await message.answer(result, reply_markup=ideas_keyboard())


@router.callback_query(F.data == "action:retry_ideas")
async def cb_retry_ideas(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    context = data.get("ideas_context")
    if not context:
        await callback.answer("Нет данных для повтора.", show_alert=True)
        return
    await callback.answer()
    thinking = await callback.message.answer("⏳ Генерирую новые идеи...")
    try:
        result = await claude.generate_ideas(context)
    except Exception as e:
        logger.error("Claude error: %s", e)
        await thinking.edit_text("Ошибка. Попробуй позже.")
        return
    await thinking.delete()
    await callback.message.answer(result, reply_markup=ideas_keyboard())


# ── PLAN ──────────────────────────────────────────────────────────────────────

@router.message(Command("plan"))
async def cmd_plan(message: Message, state: FSMContext):
    await state.set_state(PlanFlow.waiting_for_topic)
    await message.answer(
        "Введи тему или идею поста — составлю подробный план:",
        reply_markup=cancel_keyboard(),
    )


@router.callback_query(F.data == "action:plan")
async def cb_plan(callback: CallbackQuery, state: FSMContext):
    await state.set_state(PlanFlow.waiting_for_topic)
    await callback.message.edit_text(
        "Введи тему или идею поста — составлю подробный план:",
        reply_markup=cancel_keyboard(),
    )
    await callback.answer()


@router.message(PlanFlow.waiting_for_topic)
async def handle_plan_topic(message: Message, state: FSMContext):
    await state.update_data(plan_topic=message.text)
    thinking = await message.answer("⏳ Составляю план...")
    try:
        result = await claude.create_plan(message.text)
    except Exception as e:
        logger.error("Claude error: %s", e)
        await thinking.edit_text("Ошибка при обращении к Claude. Попробуй позже.")
        return
    await state.set_state(None)
    await thinking.delete()
    await message.answer(result, reply_markup=plan_keyboard())


@router.callback_query(F.data == "action:retry_plan")
async def cb_retry_plan(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    topic = data.get("plan_topic")
    if not topic:
        await callback.answer("Нет данных для повтора.", show_alert=True)
        return
    await callback.answer()
    thinking = await callback.message.answer("⏳ Составляю другой план...")
    try:
        result = await claude.create_plan(topic)
    except Exception as e:
        logger.error("Claude error: %s", e)
        await thinking.edit_text("Ошибка. Попробуй позже.")
        return
    await thinking.delete()
    await callback.message.answer(result, reply_markup=plan_keyboard())


# ── EDIT ──────────────────────────────────────────────────────────────────────

@router.message(Command("edit"))
async def cmd_edit(message: Message, state: FSMContext):
    await state.set_state(EditFlow.waiting_for_draft)
    await message.answer("Отправь черновик поста:", reply_markup=cancel_keyboard())


@router.callback_query(F.data == "action:edit")
async def cb_edit(callback: CallbackQuery, state: FSMContext):
    await state.set_state(EditFlow.waiting_for_draft)
    await callback.message.edit_text("Отправь черновик поста:", reply_markup=cancel_keyboard())
    await callback.answer()


@router.message(EditFlow.waiting_for_draft)
async def handle_edit_draft(message: Message, state: FSMContext):
    await state.update_data(edit_draft=message.text)
    await state.set_state(EditFlow.waiting_for_instructions)
    await message.answer(
        "Теперь напиши инструкцию — что нужно сделать с текстом:",
        reply_markup=cancel_keyboard(),
    )


@router.message(EditFlow.waiting_for_instructions)
async def handle_edit_instructions(message: Message, state: FSMContext):
    data = await state.get_data()
    draft = data.get("edit_draft", "")
    await state.update_data(edit_instructions=message.text)
    thinking = await message.answer("⏳ Редактирую...")
    try:
        result = await claude.edit_draft(draft, message.text)
    except Exception as e:
        logger.error("Claude error: %s", e)
        await thinking.edit_text("Ошибка при обращении к Claude. Попробуй позже.")
        return
    await state.update_data(edit_result=result)
    await state.set_state(None)
    await thinking.delete()
    await message.answer(result, reply_markup=edit_result_keyboard())


@router.callback_query(F.data == "action:retry_edit")
async def cb_retry_edit(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    draft = data.get("edit_draft")
    instructions = data.get("edit_instructions")
    if not draft or not instructions:
        await callback.answer("Нет данных для повтора.", show_alert=True)
        return
    await callback.answer()
    thinking = await callback.message.answer("⏳ Генерирую новый вариант...")
    try:
        result = await claude.edit_draft(draft, instructions)
    except Exception as e:
        logger.error("Claude error: %s", e)
        await thinking.edit_text("Ошибка. Попробуй позже.")
        return
    await state.update_data(edit_result=result)
    await thinking.delete()
    await callback.message.answer(result, reply_markup=edit_result_keyboard())


@router.callback_query(F.data == "action:edit_again")
async def cb_edit_again(callback: CallbackQuery, state: FSMContext):
    await state.set_state(EditFlow.waiting_for_instructions)
    await callback.message.edit_text(
        "Напиши новую инструкцию для редактуры:",
        reply_markup=cancel_keyboard(),
    )
    await callback.answer()


# ── DIGEST ────────────────────────────────────────────────────────────────────

@router.message(Command("digest"))
async def cmd_digest(message: Message, state: FSMContext):
    await state.set_state(DigestFlow.waiting_for_posts)
    await message.answer(
        "Отправь посты из других каналов — сделаю дайджест.\n\nРазделяй посты тремя дефисами: ---",
        reply_markup=cancel_keyboard(),
    )


@router.callback_query(F.data == "action:digest")
async def cb_digest(callback: CallbackQuery, state: FSMContext):
    await state.set_state(DigestFlow.waiting_for_posts)
    await callback.message.edit_text(
        "Отправь посты из других каналов — сделаю дайджест.\n\nРазделяй посты тремя дефисами: ---",
        reply_markup=cancel_keyboard(),
    )
    await callback.answer()


@router.message(DigestFlow.waiting_for_posts)
async def handle_digest_posts(message: Message, state: FSMContext):
    posts = [p.strip() for p in message.text.split("---") if p.strip()]
    if not posts:
        await message.answer("Нужен хотя бы один пост. Попробуй ещё раз.")
        return
    await state.update_data(digest_posts=message.text)
    thinking = await message.answer("⏳ Анализирую посты...")
    try:
        result = await claude.digest_channels(posts)
    except Exception as e:
        logger.error("Claude error: %s", e)
        await thinking.edit_text("Ошибка при обращении к Claude. Попробуй позже.")
        return
    await state.set_state(None)
    await thinking.delete()
    await message.answer(result, reply_markup=digest_keyboard())


# ── STYLE ─────────────────────────────────────────────────────────────────────

@router.message(Command("style"))
async def cmd_style(message: Message, state: FSMContext):
    await state.set_state(StyleFlow.waiting_for_posts)
    await message.answer(
        "Отправь 5–10 постов из своего канала — проанализирую стиль.\n\nРазделяй посты тремя дефисами: ---",
        reply_markup=cancel_keyboard(),
    )


@router.callback_query(F.data == "action:style")
async def cb_style(callback: CallbackQuery, state: FSMContext):
    await state.set_state(StyleFlow.waiting_for_posts)
    await callback.message.edit_text(
        "Отправь 5–10 постов из своего канала — проанализирую стиль.\n\nРазделяй посты тремя дефисами: ---",
        reply_markup=cancel_keyboard(),
    )
    await callback.answer()


@router.message(StyleFlow.waiting_for_posts)
async def handle_style_posts(message: Message, state: FSMContext):
    posts = [p.strip() for p in message.text.split("---") if p.strip()]
    if len(posts) < 3:
        await message.answer("Нужно минимум 3 поста для анализа. Разделяй их через ---")
        return
    thinking = await message.answer("⏳ Анализирую стиль... (это займёт полминуты)")
    try:
        profile = await claude.analyze_style(posts)
    except Exception as e:
        logger.error("Claude error: %s", e)
        await thinking.edit_text("Ошибка при обращении к Claude. Попробуй позже.")
        return
    await state.set_state(None)
    await thinking.delete()
    await message.answer(_format_style(profile), parse_mode="HTML", reply_markup=style_keyboard())


# ── FREE CHAT ─────────────────────────────────────────────────────────────────

@router.message(StateFilter(None))
async def free_chat(message: Message):
    if not message.text:
        return
    thinking = await message.answer("⏳")
    try:
        result = await claude.chat(message.text)
    except Exception as e:
        logger.error("Claude error: %s", e)
        await thinking.edit_text("Ошибка. Попробуй позже.")
        return
    await thinking.delete()
    await message.answer(result, reply_markup=main_menu())
