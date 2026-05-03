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

TG_LIMIT = 4096

# Лимиты входящего текста — защита от случайных огромных вставок
LIMIT_DRAFT = 3000        # черновик поста
LIMIT_INSTRUCTIONS = 500  # инструкция к редактуре
LIMIT_CONTEXT = 1000      # контекст для идей
LIMIT_TOPIC = 500         # тема для плана
LIMIT_POSTS = 8000        # посты для дайджеста / анализа стиля
LIMIT_CHAT = 2000         # сообщение в свободном чате
CHAT_HISTORY_TURNS = 3    # сколько пар user/assistant хранить в истории


async def _send(message: Message, text: str, **kwargs) -> None:
    """Отправляет текст, разбивая на части если > 4096 символов."""
    if len(text) <= TG_LIMIT:
        await message.answer(text, **kwargs)
        return
    chunks: list[str] = []
    current = ""
    for para in text.split("\n\n"):
        candidate = (current + "\n\n" + para).strip() if current else para
        if len(candidate) <= TG_LIMIT:
            current = candidate
        else:
            if current:
                chunks.append(current)
            # Параграф сам по себе больше лимита — режем по символам
            while len(para) > TG_LIMIT:
                chunks.append(para[:TG_LIMIT])
                para = para[TG_LIMIT:]
            current = para
    if current:
        chunks.append(current)
    for i, chunk in enumerate(chunks):
        await message.answer(chunk, **kwargs if i == len(chunks) - 1 else {})


async def _safe_delete(msg: Message) -> None:
    try:
        await msg.delete()
    except Exception:
        pass


async def _check_limit(message: Message, limit: int) -> bool:
    """Возвращает False и отвечает пользователю если текст превышает лимит."""
    if len(message.text) > limit:
        await message.answer(
            f"⚠️ Текст слишком длинный ({len(message.text)} символов, максимум {limit}).\n"
            "Сократи и отправь снова."
        )
        return False
    return True


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
    await state.set_state(None)  # данные (в т.ч. история чата) не стираем
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
    if not await _check_limit(message, LIMIT_CONTEXT):
        return
    await state.update_data(ideas_context=message.text)
    thinking = await message.answer("⏳ Генерирую идеи...")
    try:
        result = await claude.generate_ideas(message.text)
    except Exception as e:
        logger.error("Claude error: %s", e)
        await thinking.edit_text("Ошибка при обращении к Claude. Попробуй позже.")
        return
    await state.set_state(None)
    await _safe_delete(thinking)
    await _send(message, result, reply_markup=ideas_keyboard())


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
    await _safe_delete(thinking)
    await _send(callback.message, result, reply_markup=ideas_keyboard())


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
    if not await _check_limit(message, LIMIT_TOPIC):
        return
    await state.update_data(plan_topic=message.text)
    thinking = await message.answer("⏳ Составляю план...")
    try:
        result = await claude.create_plan(message.text)
    except Exception as e:
        logger.error("Claude error: %s", e)
        await thinking.edit_text("Ошибка при обращении к Claude. Попробуй позже.")
        return
    await state.set_state(None)
    await _safe_delete(thinking)
    await _send(message, result, reply_markup=plan_keyboard())


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
    await _safe_delete(thinking)
    await _send(callback.message, result, reply_markup=plan_keyboard())


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
    if not await _check_limit(message, LIMIT_DRAFT):
        return
    await state.update_data(edit_draft=message.text)
    await state.set_state(EditFlow.waiting_for_instructions)
    await message.answer(
        "Теперь напиши инструкцию — что нужно сделать с текстом:",
        reply_markup=cancel_keyboard(),
    )


@router.message(EditFlow.waiting_for_instructions)
async def handle_edit_instructions(message: Message, state: FSMContext):
    if not await _check_limit(message, LIMIT_INSTRUCTIONS):
        return
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
    await _safe_delete(thinking)
    await _send(message, result, reply_markup=edit_result_keyboard())


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
    await _safe_delete(thinking)
    await _send(callback.message, result, reply_markup=edit_result_keyboard())


@router.callback_query(F.data == "action:edit_again")
async def cb_edit_again(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    draft = data.get("edit_draft", "")
    preview = (draft[:150] + "…") if len(draft) > 150 else draft
    await state.set_state(EditFlow.waiting_for_instructions)
    await callback.message.edit_text(
        f"Черновик:\n<i>{preview}</i>\n\nНапиши новую инструкцию:",
        parse_mode="HTML",
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
    if not await _check_limit(message, LIMIT_POSTS):
        return
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
    await _safe_delete(thinking)
    await _send(message, result, reply_markup=digest_keyboard())


@router.callback_query(F.data == "action:retry_digest")
async def cb_retry_digest(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    raw = data.get("digest_posts")
    if not raw:
        await callback.answer("Нет данных для повтора.", show_alert=True)
        return
    await callback.answer()
    posts = [p.strip() for p in raw.split("---") if p.strip()]
    thinking = await callback.message.answer("⏳ Анализирую снова...")
    try:
        result = await claude.digest_channels(posts)
    except Exception as e:
        logger.error("Claude error: %s", e)
        await thinking.edit_text("Ошибка. Попробуй позже.")
        return
    await _safe_delete(thinking)
    await _send(callback.message, result, reply_markup=digest_keyboard())


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
    if not await _check_limit(message, LIMIT_POSTS):
        return
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
    await _safe_delete(thinking)
    await _send(message, _format_style(profile), parse_mode="HTML", reply_markup=style_keyboard())


# ── FREE CHAT ─────────────────────────────────────────────────────────────────

@router.message(StateFilter(None))
async def free_chat(message: Message, state: FSMContext):
    if not message.text or len(message.text) < 2:
        return
    if not await _check_limit(message, LIMIT_CHAT):
        return

    # Ведём историю — не более CHAT_HISTORY_TURNS пар сообщений
    data = await state.get_data()
    history: list[dict] = data.get("chat_history", [])
    history.append({"role": "user", "content": message.text})

    thinking = await message.answer("⏳")
    try:
        result = await claude.chat(history)
    except Exception as e:
        logger.error("Claude error: %s", e)
        await thinking.edit_text("Ошибка. Попробуй позже.")
        return

    history.append({"role": "assistant", "content": result})
    # Обрезаем до нужного количества пар (каждая пара = 2 элемента)
    max_msgs = CHAT_HISTORY_TURNS * 2
    if len(history) > max_msgs:
        history = history[-max_msgs:]
    await state.update_data(chat_history=history)

    await _safe_delete(thinking)
    await _send(message, result, reply_markup=main_menu())
