import logging
import os
import os as _os
from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
)

from channel_reader import fetch_all_posts, make_pools
from report_store import (
    save_report, load_latest_report,
    get_analyzed_hashes, load_latest_report_any_age, post_hash,
)
from style_context import load_style_for_user, load_style_for_channel, style_hint
from drafts_store import save_draft, load_drafts, load_draft, delete_draft
from posts_store import save_post, load_posts, load_post, delete_post
from settings_store import (
    load_settings, save_settings, update_param, reset_settings,
    PARAM_LABELS, LENGTH_LABELS,
)
from settings_format import format_for_prompt
from claude_client import ClaudeEditor
from keyboards import (
    main_menu, cancel_keyboard, ideas_keyboard,
    plan_keyboard, edit_result_keyboard, digest_keyboard, style_keyboard,
    fetch_cache_keyboard, pool_progress_keyboard,
    post_hook_keyboard, post_plan_keyboard, post_draft_keyboard,
    drafts_list_keyboard, draft_item_keyboard,
    ready_posts_list_keyboard, ready_post_item_keyboard,
    settings_main_keyboard, settings_param_keyboard, settings_length_keyboard,
)
from users_store import (
    get_user, set_channel, get_channel, get_balance,
    is_first_post_free, mark_first_post_used, mark_post_completed,
    deduct_credits, add_credits, track_usage,
    CREDITS_NEW_POST, CREDITS_IDEAS, CREDITS_PLAN, CREDITS_EDIT, CREDITS_DIGEST,
)
from payments import (buy_keyboard, no_credits_keyboard, make_invoice_prices,
                       buy_stars_keyboard, buy_rub_keyboard,
                       make_stars_prices, make_rub_prices)

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

MAX_POSTS_FOR_ANALYSIS = 100


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


async def _safe_edit(msg, text: str, **kwargs) -> None:
    """edit_text с защитой от 'message is not modified' и других Telegram-ошибок."""
    try:
        await msg.edit_text(text, **kwargs)
    except Exception as e:
        err = str(e)
        if "not modified" in err:
            pass  # уже такой текст — ок
        elif "message to edit not found" in err or "MESSAGE_ID_INVALID" in err:
            pass  # сообщение удалено — ок
        else:
            logger.warning("_safe_edit error: %s", e)


def _is_command(message: Message) -> bool:
    return bool(message.text and message.text.startswith("/"))


async def _check_limit(message: Message, limit: int) -> bool:
    """Возвращает False и отвечает пользователю если текст превышает лимит."""
    if len(message.text) > limit:
        await message.answer(
            f"⚠️ Текст слишком длинный ({len(message.text)} символов, максимум {limit}).\n"
            "Сократи и отправь снова."
        )
        return False
    return True


async def _check_credits(source, state: FSMContext, cost: int) -> bool:
    """Проверяет баланс. Если не хватает — показывает предложение купить. Возвращает True если ок."""
    user_id = source.from_user.id
    # Для новых постов — первый бесплатный
    if cost == CREDITS_NEW_POST and is_first_post_free(user_id):
        return True
    if deduct_credits(user_id, cost):
        return True
    # Не хватает кредитов
    balance = get_balance(user_id)
    text = (
        f"💳 <b>Кредиты закончились</b> (баланс: {balance})\n\n"
        f"Для этого действия нужно <b>{cost} кредит(а)</b>.\n"
        "Пополни баланс чтобы продолжить:"
    )
    if hasattr(source, 'message'):
        # CallbackQuery
        await source.answer()
        await source.message.answer(text, parse_mode="HTML", reply_markup=no_credits_keyboard())
    else:
        # Message
        await source.answer(text, parse_mode="HTML", reply_markup=no_credits_keyboard())
    return False


class IdeasFlow(StatesGroup):
    waiting_for_context = State()
    showed_ideas = State()   # идеи показаны, ждём выбора цифрой или нового запроса


class PlanFlow(StatesGroup):
    waiting_for_topic = State()


class EditFlow(StatesGroup):
    waiting_for_draft = State()
    waiting_for_instructions = State()


class DigestFlow(StatesGroup):
    waiting_for_posts = State()


class StyleFlow(StatesGroup):
    waiting_for_posts = State()


class PostFlow(StatesGroup):
    waiting_for_topic = State()
    reviewing_hook = State()
    waiting_plan_edit = State()
    reviewing_plan = State()
    reviewing_draft = State()
    waiting_draft_edit = State()


class ChannelFlow(StatesGroup):
    waiting_for_channel = State()


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
    user = get_user(message.from_user.id)
    is_new = not user.get("free_post_used") and user.get("total_posts", 0) == 0

    if is_new:
        text = (
            "👋 Привет! Я помогаю создавать посты для Telegram-канала.\n\n"
            "<b>Что умею:</b>\n"
            "✍️ Писать посты в твоём стиле\n"
            "💡 Генерировать идеи и хуки\n"
            "✏️ Редактировать черновики\n\n"
            "🎁 <b>Первый пост — бесплатно</b>, включая все правки.\n\n"
            "Добавь свой канал через ⚙️ Настройки → 📡 Мой канал "
            "чтобы бот писал в твоём стиле.\n\n"
            "Выбери действие:"
        )
    else:
        balance = get_balance(message.from_user.id)
        text = f"👋 С возвращением! Баланс: <b>{balance} кредитов</b>\n\nВыбери действие:"

    await message.answer(text, parse_mode="HTML", reply_markup=main_menu())


# ── /cancel / action:cancel ───────────────────────────────────────────────────

@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Отменено. Выбери действие:", reply_markup=main_menu())


@router.callback_query(F.data == "action:cancel")
async def cb_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await _safe_edit(callback.message, "Отменено. Выбери действие:", reply_markup=main_menu())
    await callback.answer()


# ── action:menu ───────────────────────────────────────────────────────────────

@router.callback_query(F.data == "action:menu")
async def cb_menu(callback: CallbackQuery, state: FSMContext):
    current = await state.get_state()
    # Автосохранение при выходе из PostFlow если есть хоть какой-то контент
    if current and "PostFlow" in current:
        data = await state.get_data()
        if data.get("post_topic"):
            try:
                draft_id = save_draft(callback.from_user.id, data)
                await state.update_data(draft_id=draft_id)
            except Exception as e:
                logger.error("Ошибка сохранения черновика: %s", e)
    await state.set_state(None)  # данные не стираем
    await _safe_edit(callback.message, "Выбери действие:", reply_markup=main_menu())
    await callback.answer()


# ── IDEAS ─────────────────────────────────────────────────────────────────────

@router.message(Command("ideas"))
async def cmd_ideas(message: Message, state: FSMContext):
    if not await _check_credits(message, state, CREDITS_IDEAS):
        return
    style = load_style_for_user(message.from_user.id)
    await state.set_state(IdeasFlow.waiting_for_context)
    await state.update_data(ideas_style=style)
    await message.answer(
        "Расскажи, что сейчас происходит или что тебя занимает — придумаю идеи для постов:"
        + style_hint(style),
        parse_mode="HTML",
        reply_markup=cancel_keyboard(),
    )


@router.callback_query(F.data == "action:ideas")
async def cb_ideas(callback: CallbackQuery, state: FSMContext):
    if not await _check_credits(callback, state, CREDITS_IDEAS):
        return
    style = load_style_for_user(callback.from_user.id)
    await state.set_state(IdeasFlow.waiting_for_context)
    await state.update_data(ideas_style=style)
    await _safe_edit(callback.message,
        "Расскажи, что сейчас происходит или что тебя занимает — придумаю идеи для постов:"
        + style_hint(style),
        parse_mode="HTML",
        reply_markup=cancel_keyboard(),
    )
    await callback.answer()


@router.message(IdeasFlow.waiting_for_context)
async def handle_ideas_context(message: Message, state: FSMContext):
    if _is_command(message):
        return
    if not await _check_limit(message, LIMIT_CONTEXT):
        return
    data = await state.get_data()
    style = data.get("ideas_style", "")
    await state.update_data(ideas_context=message.text)
    thinking = await message.answer("⏳ Генерирую идеи...")
    try:
        result = await claude.generate_ideas(message.text, style=style)
    except Exception as e:
        logger.error("Claude error: %s", e)
        await thinking.edit_text("Ошибка при обращении к Claude. Попробуй позже.")
        return
    await state.update_data(ideas_result=result)
    await state.set_state(IdeasFlow.showed_ideas)
    await _safe_delete(thinking)
    await _send(
        message,
        result + "\n\n<i>Ответь цифрой, чтобы сразу начать пост по этой идее.</i>",
        parse_mode="HTML",
        reply_markup=ideas_keyboard(),
    )


@router.callback_query(F.data == "action:retry_ideas")
async def cb_retry_ideas(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    context = data.get("ideas_context")
    style = data.get("ideas_style", "")
    if not context:
        await callback.answer("Нет данных для повтора.", show_alert=True)
        return
    await callback.answer()
    thinking = await callback.message.answer("⏳ Генерирую новые идеи...")
    try:
        result = await claude.generate_ideas(context, style=style)
    except Exception as e:
        logger.error("Claude error: %s", e)
        await thinking.edit_text("Ошибка. Попробуй позже.")
        return
    await state.update_data(ideas_result=result)
    await state.set_state(IdeasFlow.showed_ideas)
    await _safe_delete(thinking)
    await _send(
        callback.message,
        result + "\n\n<i>Ответь цифрой, чтобы сразу начать пост по этой идее.</i>",
        parse_mode="HTML",
        reply_markup=ideas_keyboard(),
    )


@router.message(IdeasFlow.showed_ideas)
async def handle_idea_pick(message: Message, state: FSMContext):
    """Пользователь отвечает цифрой → стартуем PostFlow с этой идеей как темой."""
    if _is_command(message):
        return
    data = await state.get_data()
    ideas_text = data.get("ideas_result", "")
    style = data.get("ideas_style", "")
    text = message.text.strip()

    if text.isdigit() and 1 <= int(text) <= 9:
        topic = _extract_idea(ideas_text, int(text))
        if not topic:
            await message.answer("Не смог распознать эту идею — напиши тему своими словами.")
            return
    else:
        if not await _check_limit(message, LIMIT_TOPIC):
            return
        topic = text  # своя тема

    # Стартуем PostFlow с готовой темой, минуя повторный запрос
    settings_block = format_for_prompt(load_settings(message.from_user.id))
    await state.update_data(
        post_topic=topic, post_hooks_text=None, post_chosen_hook=None,
        post_plan=None, post_draft=None, draft_id=None,
        post_style=style, post_settings=settings_block,
    )
    await state.set_state(PostFlow.waiting_for_topic)

    thinking = await message.answer(f"✍️ Тема: <i>{topic}</i>\n\n⏳ Генерирую варианты хука…", parse_mode="HTML")
    try:
        hooks_text = await claude.generate_hooks(topic, style=style, settings=settings_block)
    except Exception as e:
        logger.error("Claude error: %s", e)
        await thinking.edit_text("Ошибка. Попробуй позже.")
        return

    await state.update_data(post_hooks_text=hooks_text)
    await state.set_state(PostFlow.reviewing_hook)
    await _safe_delete(thinking)
    await _send(
        message,
        f"🪝 <b>Варианты хука:</b>\n\n{hooks_text}\n\n"
        "Ответь <b>цифрой</b> (1, 2 или 3) чтобы выбрать хук.\n"
        "Или напиши <b>свой вариант</b> первой фразы.",
        parse_mode="HTML",
        reply_markup=post_hook_keyboard(),
    )


# ── PLAN ──────────────────────────────────────────────────────────────────────

@router.message(Command("plan"))
async def cmd_plan(message: Message, state: FSMContext):
    if not await _check_credits(message, state, CREDITS_PLAN):
        return
    style = load_style_for_user(message.from_user.id)
    await state.set_state(PlanFlow.waiting_for_topic)
    await state.update_data(plan_style=style)
    await message.answer(
        "Введи тему или идею поста — составлю подробный план:"
        + style_hint(style),
        parse_mode="HTML",
        reply_markup=cancel_keyboard(),
    )


@router.callback_query(F.data == "action:plan")
async def cb_plan(callback: CallbackQuery, state: FSMContext):
    if not await _check_credits(callback, state, CREDITS_PLAN):
        return
    style = load_style_for_user(callback.from_user.id)
    await state.set_state(PlanFlow.waiting_for_topic)
    await state.update_data(plan_style=style)
    await _safe_edit(callback.message,
        "Введи тему или идею поста — составлю подробный план:"
        + style_hint(style),
        parse_mode="HTML",
        reply_markup=cancel_keyboard(),
    )
    await callback.answer()


@router.message(PlanFlow.waiting_for_topic)
async def handle_plan_topic(message: Message, state: FSMContext):
    if _is_command(message):
        return
    if not await _check_limit(message, LIMIT_TOPIC):
        return
    data = await state.get_data()
    style = data.get("plan_style", "")
    await state.update_data(plan_topic=message.text)
    thinking = await message.answer("⏳ Составляю план...")
    try:
        result = await claude.create_plan(message.text, style=style)
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
    style = data.get("plan_style", "")
    if not topic:
        await callback.answer("Нет данных для повтора.", show_alert=True)
        return
    await callback.answer()
    thinking = await callback.message.answer("⏳ Составляю другой план...")
    try:
        result = await claude.create_plan(topic, style=style)
    except Exception as e:
        logger.error("Claude error: %s", e)
        await thinking.edit_text("Ошибка. Попробуй позже.")
        return
    await _safe_delete(thinking)
    await _send(callback.message, result, reply_markup=plan_keyboard())


# ── EDIT ──────────────────────────────────────────────────────────────────────

@router.message(Command("edit"))
async def cmd_edit(message: Message, state: FSMContext):
    if not await _check_credits(message, state, CREDITS_EDIT):
        return
    style = load_style_for_user(message.from_user.id)
    await state.set_state(EditFlow.waiting_for_draft)
    await state.update_data(edit_style=style)
    await message.answer(
        "Отправь черновик поста:" + style_hint(style),
        parse_mode="HTML",
        reply_markup=cancel_keyboard(),
    )


@router.callback_query(F.data == "action:edit")
async def cb_edit(callback: CallbackQuery, state: FSMContext):
    if not await _check_credits(callback, state, CREDITS_EDIT):
        return
    style = load_style_for_user(callback.from_user.id)
    await state.set_state(EditFlow.waiting_for_draft)
    await state.update_data(edit_style=style)
    await _safe_edit(callback.message,
        "Отправь черновик поста:" + style_hint(style),
        parse_mode="HTML",
        reply_markup=cancel_keyboard(),
    )
    await callback.answer()


@router.message(EditFlow.waiting_for_draft)
async def handle_edit_draft(message: Message, state: FSMContext):
    if _is_command(message):
        return
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
    if _is_command(message):
        return
    if not await _check_limit(message, LIMIT_INSTRUCTIONS):
        return
    data = await state.get_data()
    draft = data.get("edit_draft", "")
    style = data.get("edit_style", "")
    await state.update_data(edit_instructions=message.text)
    thinking = await message.answer("⏳ Редактирую...")
    try:
        result = await claude.edit_draft(draft, message.text, style=style)
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
    style = data.get("edit_style", "")
    if not draft or not instructions:
        await callback.answer("Нет данных для повтора.", show_alert=True)
        return
    await callback.answer()
    thinking = await callback.message.answer("⏳ Генерирую новый вариант...")
    try:
        result = await claude.edit_draft(draft, instructions, style=style)
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
    await _safe_edit(callback.message,
        f"Черновик:\n<i>{preview}</i>\n\nНапиши новую инструкцию:",
        parse_mode="HTML",
        reply_markup=cancel_keyboard(),
    )
    await callback.answer()


# ── DIGEST ────────────────────────────────────────────────────────────────────

@router.message(Command("digest"))
async def cmd_digest(message: Message, state: FSMContext):
    if not await _check_credits(message, state, CREDITS_DIGEST):
        return
    await state.set_state(DigestFlow.waiting_for_posts)
    await message.answer(
        "Отправь посты из других каналов — сделаю дайджест.\n\nРазделяй посты тремя дефисами: ---",
        reply_markup=cancel_keyboard(),
    )


@router.callback_query(F.data == "action:digest")
async def cb_digest(callback: CallbackQuery, state: FSMContext):
    if not await _check_credits(callback, state, CREDITS_DIGEST):
        return
    await state.set_state(DigestFlow.waiting_for_posts)
    await _safe_edit(callback.message,
        "Отправь посты из других каналов — сделаю дайджест.\n\nРазделяй посты тремя дефисами: ---",
        reply_markup=cancel_keyboard(),
    )
    await callback.answer()


@router.message(DigestFlow.waiting_for_posts)
async def handle_digest_posts(message: Message, state: FSMContext):
    if _is_command(message):
        return
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
    await callback.answer()
    user_id = callback.from_user.id
    channel = os.getenv("CHANNEL_USERNAME", "").strip()
    if not channel:
        await _safe_edit(
            callback.message,
            "⚠️ Канал не задан.\n\n"
            "Добавь в <code>.env</code>:\n<code>CHANNEL_USERNAME=@username</code>\n\n"
            "Или используй /style чтобы вручную вставить посты для анализа.",
            parse_mode="HTML",
            reply_markup=main_menu(),
        )
        return
    # Проверяем кэш — та же логика что в /fetch_channel
    cached = load_latest_report(channel, user_id)
    if cached:
        from datetime import datetime
        dt = datetime.fromisoformat(cached["fetched_at"])
        date_str = dt.strftime("%d.%m.%Y %H:%M")
        await state.update_data(fetch_channel=channel, fetch_cached=cached)
        await _safe_edit(
            callback.message,
            f"📁 Найден отчёт от <b>{date_str}</b>\n"
            f"Всего постов: <b>{cached['total_fetched']}</b> | "
            f"Проанализировано: <b>{cached['posts_for_analysis']}</b>\n\n"
            "Использовать кэш или выгрузить заново?",
            parse_mode="HTML",
            reply_markup=fetch_cache_keyboard(),
        )
        return
    await _safe_edit(callback.message, f"⏳ Подключаюсь к {channel}…")
    await _do_fetch_and_analyze(callback.message, state, channel, user_id)


@router.message(StyleFlow.waiting_for_posts)
async def handle_style_posts(message: Message, state: FSMContext):
    if _is_command(message):
        return
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


# ── FETCH CHANNEL ─────────────────────────────────────────────────────────────

async def _do_fetch_and_analyze(message: Message, state: FSMContext, channel: str, user_id: int) -> None:
    """
    Выгружает посты, определяет новые (не попавшие в прошлый анализ),
    разбивает только их на пулы и запускает анализ первого пула.
    """
    thinking = await message.answer(f"⏳ Читаю все посты из {channel}…")
    try:
        all_posts, total = await fetch_all_posts(channel)
    except Exception as e:
        logger.error("Fetch error: %s", e)
        await thinking.edit_text(str(e) if isinstance(e, RuntimeError) else f"Не удалось прочитать канал.\n{e}")
        return

    if total < 3:
        await thinking.edit_text(f"Нашёл только {total} постов — недостаточно для анализа.")
        return

    # ── Инкрементальная логика ────────────────────────────────────────────────
    analyzed_hashes = get_analyzed_hashes(channel, user_id)
    existing_profile = None

    if analyzed_hashes:
        new_posts = [p for p in all_posts if post_hash(p) not in analyzed_hashes]
        old_count = total - len(new_posts)

        if not new_posts:
            # Новых постов нет — сразу показываем готовый профиль
            cached = load_latest_report_any_age(channel, user_id)
            await thinking.edit_text(
                f"✅ Новых постов нет.\n"
                f"Канал уже полностью проанализирован (<b>{old_count}</b> постов).\n\n"
                f"Актуальный профиль стиля:",
                parse_mode="HTML",
            )
            if cached:
                profile = cached.get("analysis", {})
                await _send(message, _format_style(profile), parse_mode="HTML", reply_markup=style_keyboard())
            return

        # Есть новые посты — грузим старый профиль для слияния
        cached = load_latest_report_any_age(channel, user_id)
        existing_profile = cached.get("analysis") if cached else None
        posts_to_analyze = new_posts

        await thinking.edit_text(
            f"🆕 Найдено <b>{len(new_posts)}</b> новых постов\n"
            f"(уже проанализировано ранее: {old_count} из {total})\n\n"
            f"Запускаю анализ только новых…",
            parse_mode="HTML",
        )
    else:
        # Первый анализ — берём все посты
        posts_to_analyze = all_posts

    # Ограничение на количество постов для анализа
    posts_to_analyze = posts_to_analyze[:MAX_POSTS_FOR_ANALYSIS]

    pools = make_pools(posts_to_analyze)
    await state.update_data(
        fetch_channel=channel,
        fetch_all_posts=all_posts,          # все посты канала (для сохранения в отчёт)
        fetch_total=total,
        fetch_pools=pools,                  # пулы только из новых постов
        fetch_pool_idx=0,
        fetch_pool_analyses=[],
        fetch_existing_profile=existing_profile,   # старый профиль для слияния
        fetch_new_count=len(posts_to_analyze),     # сколько новых идёт в анализ
        fetch_user_id=user_id,
    )
    await _analyze_pool(message, state, user_id=user_id, thinking=thinking)


async def _analyze_pool(message: Message, state: FSMContext, user_id: int, thinking=None) -> None:
    """Анализирует текущий пул (из новых постов) и показывает результат."""
    data = await state.get_data()
    pools = data.get("fetch_pools", [])
    idx = data.get("fetch_pool_idx", 0)
    total = data.get("fetch_total", 0)
    new_count = data.get("fetch_new_count", total)
    prev_analyses = data.get("fetch_pool_analyses", [])

    pool = pools[idx]
    total_pools = len(pools)
    is_incremental = new_count < total

    # Подпись к сообщению о прогрессе
    if is_incremental:
        progress_text = (
            f"⏳ Анализирую пул {idx + 1}/{total_pools} "
            f"({len(pool)} из <b>{new_count} новых</b> постов | всего в канале: {total})…"
        )
    else:
        progress_text = (
            f"⏳ Анализирую пул {idx + 1}/{total_pools} "
            f"({len(pool)} постов из {total})…"
        )

    if thinking:
        await thinking.edit_text(progress_text, parse_mode="HTML")
    else:
        thinking = await message.answer(progress_text, parse_mode="HTML")

    try:
        profile = await claude.analyze_style(pool)
    except Exception as e:
        logger.error("Claude error: %s", e)
        await thinking.edit_text("Ошибка при анализе. Попробуй позже.")
        return

    new_analyses = prev_analyses + [profile]
    await state.update_data(fetch_pool_analyses=new_analyses)
    await _safe_delete(thinking)

    if is_incremental:
        header = (
            f"📊 <b>Пул {idx + 1}/{total_pools}</b> — {len(pool)} из <b>{new_count} новых</b> постов\n"
            f"(всего в канале: {total})\n\n"
        )
    else:
        header = (
            f"📊 <b>Пул {idx + 1}/{total_pools}</b> — постов {len(pool)} "
            f"(всего в канале: {total})\n\n"
        )
    await message.answer(header, parse_mode="HTML")
    await _send(
        message,
        _format_style(profile),
        parse_mode="HTML",
        reply_markup=pool_progress_keyboard(idx, total_pools),
    )


@router.message(Command("fetch_channel"))
async def cmd_fetch_channel(message: Message, state: FSMContext):
    user_id = message.from_user.id
    args = message.text.split(maxsplit=1)
    channel = args[1].strip() if len(args) > 1 else os.getenv("CHANNEL_USERNAME", "")

    if not channel:
        await message.answer(
            "Укажи канал: <code>/fetch_channel @username</code>\n"
            "Или добавь <code>CHANNEL_USERNAME=@username</code> в .env",
            parse_mode="HTML",
        )
        return

    # Проверяем кэш
    cached = load_latest_report(channel, user_id)
    if cached:
        from datetime import datetime
        dt = datetime.fromisoformat(cached["fetched_at"])
        date_str = dt.strftime("%d.%m.%Y %H:%M")
        await state.update_data(fetch_channel=channel, fetch_cached=cached)
        await message.answer(
            f"📁 Найден отчёт от <b>{date_str}</b>\n"
            f"Всего постов: <b>{cached['total_fetched']}</b> | "
            f"Проанализировано: <b>{cached['posts_for_analysis']}</b>\n\n"
            "Использовать кэш или выгрузить заново?",
            parse_mode="HTML",
            reply_markup=fetch_cache_keyboard(),
        )
        return

    await _do_fetch_and_analyze(message, state, channel, user_id)


@router.callback_query(F.data == "fetch:next_pool")
async def cb_next_pool(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    data = await state.get_data()
    idx = data.get("fetch_pool_idx", 0)
    await state.update_data(fetch_pool_idx=idx + 1)
    await callback.answer()
    await _analyze_pool(callback.message, state, user_id=user_id)


@router.callback_query(F.data == "fetch:merge")
async def cb_merge_analyses(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    data = await state.get_data()
    analyses = data.get("fetch_pool_analyses", [])
    existing_profile = data.get("fetch_existing_profile")  # старый профиль (если инкремент)
    channel = data.get("fetch_channel", "")
    all_posts = data.get("fetch_all_posts", [])
    total = data.get("fetch_total", 0)
    new_count = data.get("fetch_new_count", total)

    if not analyses:
        await callback.answer("Нет данных для объединения.", show_alert=True)
        return

    await callback.answer()
    thinking = await callback.message.answer("⏳ Объединяю все анализы в финальный профиль…")

    # Включаем старый профиль в слияние если анализ был инкрементальным
    all_to_merge = ([existing_profile] if existing_profile else []) + analyses

    try:
        if len(all_to_merge) == 1:
            # Единственный пул — merge не нужен
            final_profile = all_to_merge[0]
        else:
            final_profile = await claude.merge_style_analyses(all_to_merge)
    except Exception as e:
        logger.error("Claude error: %s", e)
        await thinking.edit_text("Ошибка при объединении. Попробуй позже.")
        return

    report_path = save_report(
        channel, all_posts, total, final_profile,
        user_id=user_id, all_posts=all_posts, pool_analyses=analyses,
    )
    await _safe_delete(thinking)

    is_incremental = existing_profile is not None
    if is_incremental:
        header = (
            f"✅ <b>Профиль обновлён: {channel}</b>\n"
            f"Добавлено новых постов: <b>{new_count}</b> | всего в канале: <b>{total}</b>\n"
            f"Сохранено: <code>{report_path.name}</code>\n\n"
        )
    else:
        header = (
            f"✅ <b>Финальный профиль {channel}</b>\n"
            f"Проанализировано постов: <b>{total}</b> ({len(analyses)} пулов)\n"
            f"Сохранено: <code>{report_path.name}</code>\n\n"
        )
    await callback.message.answer(header, parse_mode="HTML")
    await _send(callback.message, _format_style(final_profile), parse_mode="HTML", reply_markup=style_keyboard())


@router.callback_query(F.data == "fetch:use_cache")
async def cb_fetch_use_cache(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    cached = data.get("fetch_cached")
    if not cached:
        await callback.answer("Кэш не найден.", show_alert=True)
        return
    await callback.answer()
    await _safe_edit(callback.message, "Загружаю из кэша…")
    profile = cached.get("analysis", {})
    await _safe_delete(callback.message)
    from datetime import datetime
    dt = datetime.fromisoformat(cached["fetched_at"])
    summary = (
        f"📊 <b>Из кэша ({dt.strftime('%d.%m.%Y')})</b>\n"
        f"Постов в канале: <b>{cached['total_fetched']}</b> | "
        f"Проанализировано: <b>{cached['posts_for_analysis']}</b>\n\n"
    )
    await callback.message.answer(summary, parse_mode="HTML")
    await _send(callback.message, _format_style(profile), parse_mode="HTML", reply_markup=style_keyboard())


@router.callback_query(F.data == "fetch:refresh")
async def cb_fetch_refresh(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    data = await state.get_data()
    channel = data.get("fetch_channel", os.getenv("CHANNEL_USERNAME", ""))
    await callback.answer()
    await _safe_edit(callback.message, "Запускаю обновление…")
    await _do_fetch_and_analyze(callback.message, state, channel, user_id)


# ── NEW POST ──────────────────────────────────────────────────────────────────

import re as _re

def _extract_hook(hooks_text: str, n: int) -> str:
    """Извлекает n-й хук из нумерованного списка Claude."""
    pattern = rf'(?:^|\n)\s*{n}[.)]\s*(.+?)(?=\n\s*[123][.)]\s|\Z)'
    match = _re.search(pattern, hooks_text, _re.DOTALL)
    if match:
        return match.group(1).strip()
    # Фолбэк — вернуть первую строку
    return hooks_text.split('\n')[0].strip()


def _extract_idea(ideas_text: str, n: int) -> str:
    """Извлекает n-ю идею из нумерованного списка Claude. Возвращает первую строку (заголовок)."""
    pattern = rf'(?m)^\s*{n}[.)]\s+(.+?)(?=\n\s*\d+[.)]\s|\Z)'
    match = _re.search(pattern, ideas_text, _re.DOTALL)
    if not match:
        return ""
    full = match.group(1).strip()
    # Берём первую строку как заголовок, убираем markdown **...**
    first_line = full.split('\n')[0].strip()
    first_line = _re.sub(r'\*\*(.+?)\*\*', r'\1', first_line)
    first_line = _re.sub(r'^\*+|\*+$', '', first_line).strip()
    return first_line or full[:120]


def _post_progress_label(data: dict) -> str:
    """Возвращает текстовое описание текущего шага незаконченного поста."""
    topic = data.get("post_topic", "")
    preview = (topic[:60] + "…") if len(topic) > 60 else topic
    if data.get("post_draft"):
        return f"черновик готов — <i>{preview}</i>"
    if data.get("post_plan"):
        return f"план готов — <i>{preview}</i>"
    if data.get("post_hooks_text"):
        return f"хуки готовы — <i>{preview}</i>"
    return ""


async def _start_new_post(target, state: FSMContext, user_id: int, edit: bool = False):
    """Очищает старые данные поста и начинает флоу с темы.

    target — Message или CallbackQuery.message.
    user_id — id пользователя (для подгрузки настроек тона).
    edit=True → редактирует существующее сообщение (для callback-контекста),
    edit=False → отправляет новое (для command-контекста).
    """
    style = load_style_for_user(user_id)
    settings_block = format_for_prompt(load_settings(user_id))
    # Чистим только post_* ключи + draft_id, остальные данные (чат, стиль анализа) не трогаем
    await state.update_data(
        post_topic=None, post_hooks_text=None, post_chosen_hook=None,
        post_plan=None, post_draft=None, draft_id=None,
        post_style=style, post_settings=settings_block,
    )
    # Если первый пост — отметить использованным (списание было в check_credits)
    if is_first_post_free(user_id):
        mark_first_post_used(user_id)
    await state.set_state(PostFlow.waiting_for_topic)
    text = (
        "✍️ <b>Новый пост</b>\n\nО чём будем писать? Опиши тему или идею:"
        + style_hint(style)
    )
    if edit:
        await _safe_edit(target, text, parse_mode="HTML", reply_markup=cancel_keyboard())
    else:
        await target.answer(text, parse_mode="HTML", reply_markup=cancel_keyboard())


async def _resume_post(target, state: FSMContext, data: dict):
    """Восстанавливает флоу с последнего незаконченного шага."""
    if data.get("post_draft"):
        await state.set_state(PostFlow.reviewing_draft)
        await target.answer("📝 <b>Продолжаем — черновик:</b>", parse_mode="HTML")
        await _send(target, data["post_draft"], reply_markup=post_draft_keyboard())
    elif data.get("post_plan"):
        await state.set_state(PostFlow.reviewing_plan)
        hook_line = f"\n🪝 Хук: <i>{data['post_chosen_hook']}</i>\n" if data.get("post_chosen_hook") else ""
        await target.answer(f"📋 <b>Продолжаем — план:{hook_line}</b>", parse_mode="HTML")
        await _send(target, data["post_plan"], reply_markup=post_plan_keyboard())
    elif data.get("post_hooks_text"):
        await state.set_state(PostFlow.reviewing_hook)
        await _send(
            target,
            f"🪝 <b>Продолжаем — варианты хука:</b>\n\n{data['post_hooks_text']}\n\n"
            "Ответь <b>цифрой</b> (1, 2 или 3) или напиши <b>свой вариант</b>.",
            parse_mode="HTML",
            reply_markup=post_hook_keyboard(),
        )
    else:
        # _resume_post вызывается уже с подгруженными настройками — фолбэк не нужен
        await target.answer("✍️ Не могу восстановить — начни заново через меню.")


@router.message(Command("new_post"))
async def cmd_new_post(message: Message, state: FSMContext):
    if not await _check_credits(message, state, CREDITS_NEW_POST):
        return
    await _start_new_post(message, state, message.from_user.id)


@router.callback_query(F.data == "action:new_post")
async def cb_new_post(callback: CallbackQuery, state: FSMContext):
    if not await _check_credits(callback, state, CREDITS_NEW_POST):
        return
    await callback.answer()
    await _start_new_post(callback.message, state, callback.from_user.id, edit=True)


@router.message(PostFlow.waiting_for_topic)
async def post_handle_topic(message: Message, state: FSMContext):
    if _is_command(message):
        return
    if not await _check_limit(message, LIMIT_TOPIC):
        return
    data = await state.get_data()
    style = data.get("post_style", "")
    settings_block = data.get("post_settings", "")
    await state.update_data(post_topic=message.text)

    thinking = await message.answer("⏳ Генерирую варианты хука…")
    try:
        hooks_text = await claude.generate_hooks(message.text, style=style, settings=settings_block)
    except Exception as e:
        logger.error("Claude error: %s", e)
        await thinking.edit_text("Ошибка. Попробуй позже.")
        return

    await state.update_data(post_hooks_text=hooks_text)
    await state.set_state(PostFlow.reviewing_hook)
    await _safe_delete(thinking)
    await _send(
        message,
        f"🪝 <b>Варианты хука:</b>\n\n{hooks_text}\n\n"
        "Ответь <b>цифрой</b> (1, 2 или 3) чтобы выбрать хук.\n"
        "Или напиши <b>свой вариант</b> первой фразы.",
        parse_mode="HTML",
        reply_markup=post_hook_keyboard(),
    )


@router.message(PostFlow.reviewing_hook)
async def post_handle_hook_pick(message: Message, state: FSMContext):
    """Пользователь выбирает хук цифрой или пишет свой."""
    if _is_command(message):
        return
    data = await state.get_data()
    hooks_text = data.get("post_hooks_text", "")
    topic = data.get("post_topic", "")
    style = data.get("post_style", "")
    settings_block = data.get("post_settings", "")

    text = message.text.strip()
    if text in ("1", "2", "3"):
        chosen_hook = _extract_hook(hooks_text, int(text))
    else:
        if not await _check_limit(message, LIMIT_TOPIC):
            return
        chosen_hook = text  # свой вариант

    await _generate_plan(message, state, topic, chosen_hook, style, settings_block)


@router.callback_query(F.data == "post:retry_hooks")
async def post_retry_hooks(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    topic = data.get("post_topic", "")
    style = data.get("post_style", "")
    settings_block = data.get("post_settings", "")
    await callback.answer()
    thinking = await callback.message.answer("⏳ Генерирую новые варианты…")
    try:
        hooks_text = await claude.generate_hooks(topic, style=style, settings=settings_block)
    except Exception as e:
        logger.error("Claude error: %s", e)
        await thinking.edit_text("Ошибка. Попробуй позже.")
        return
    await state.update_data(post_hooks_text=hooks_text)
    await _safe_delete(thinking)
    await _send(
        callback.message,
        f"🪝 <b>Новые варианты хука:</b>\n\n{hooks_text}\n\n"
        "Ответь <b>цифрой</b> (1, 2 или 3) или напиши <b>свой вариант</b>.",
        parse_mode="HTML",
        reply_markup=post_hook_keyboard(),
    )


@router.callback_query(F.data == "post:skip_hook")
async def post_skip_hook(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    topic = data.get("post_topic", "")
    style = data.get("post_style", "")
    settings_block = data.get("post_settings", "")
    await callback.answer()
    await _generate_plan(callback.message, state, topic, "", style, settings_block)


async def _generate_plan(message: Message, state: FSMContext, topic: str, hook: str, style: str, settings: str = ""):
    """Генерирует план и переводит в состояние reviewing_plan."""
    await state.update_data(post_chosen_hook=hook)
    await state.set_state(PostFlow.reviewing_plan)
    thinking = await message.answer("⏳ Составляю план поста…")
    try:
        plan = await claude.create_plan(
            f"{topic}" + (f"\nХук: {hook}" if hook else ""),
            style=style, settings=settings,
        )
    except Exception as e:
        logger.error("Claude error: %s", e)
        await thinking.edit_text("Ошибка. Попробуй позже.")
        return
    await state.update_data(post_plan=plan)
    await _safe_delete(thinking)
    hook_line = f"\n🪝 Хук: <i>{hook}</i>\n" if hook else ""
    await message.answer(
        f"📋 <b>План поста:</b>{hook_line}\n",
        parse_mode="HTML",
    )
    await _send(message, plan, reply_markup=post_plan_keyboard())


@router.callback_query(F.data == "post:retry_plan")
async def post_retry_plan(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    topic = data.get("post_topic", "")
    hook = data.get("post_chosen_hook", "")
    style = data.get("post_style", "")
    settings_block = data.get("post_settings", "")
    await callback.answer()
    await _generate_plan(callback.message, state, topic, hook, style, settings_block)


@router.callback_query(F.data == "post:edit_plan")
async def post_edit_plan(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(PostFlow.waiting_plan_edit)
    # Убираем кнопки с плана — текст плана остаётся виден выше
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.message.answer(
        "✏️ Напиши что изменить в плане:",
        reply_markup=cancel_keyboard(),
    )


@router.message(PostFlow.waiting_plan_edit)
async def post_handle_plan_edit(message: Message, state: FSMContext):
    if _is_command(message):
        return
    if not await _check_limit(message, LIMIT_INSTRUCTIONS):
        return
    data = await state.get_data()
    plan = data.get("post_plan", "")
    style = data.get("post_style", "")
    settings_block = data.get("post_settings", "")
    await state.set_state(PostFlow.reviewing_plan)
    thinking = await message.answer("⏳ Корректирую план…")
    try:
        new_plan = await claude.edit_draft(plan, message.text, style=style, settings=settings_block)
    except Exception as e:
        logger.error("Claude error: %s", e)
        await thinking.edit_text("Ошибка. Попробуй позже.")
        return
    await state.update_data(post_plan=new_plan)
    await _safe_delete(thinking)
    await message.answer("📋 <b>Обновлённый план:</b>", parse_mode="HTML")
    await _send(message, new_plan, reply_markup=post_plan_keyboard())


@router.callback_query(F.data == "post:write_draft")
async def post_write_draft(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    topic = data.get("post_topic", "")
    hook = data.get("post_chosen_hook", "")
    plan = data.get("post_plan", "")
    style = data.get("post_style", "")
    settings_block = data.get("post_settings", "")
    await callback.answer()
    thinking = await callback.message.answer("⏳ Пишу черновик…")
    try:
        draft = await claude.write_draft_from_plan(topic, hook, plan, style=style, settings=settings_block)
    except Exception as e:
        logger.error("Claude error: %s", e)
        await thinking.edit_text("Ошибка. Попробуй позже.")
        return
    await state.update_data(post_draft=draft)
    await state.set_state(PostFlow.reviewing_draft)
    await _safe_delete(thinking)
    await callback.message.answer("📝 <b>Черновик:</b>", parse_mode="HTML")
    await _send(callback.message, draft, reply_markup=post_draft_keyboard())


@router.callback_query(F.data == "post:retry_draft")
async def post_retry_draft(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    topic = data.get("post_topic", "")
    hook = data.get("post_chosen_hook", "")
    plan = data.get("post_plan", "")
    style = data.get("post_style", "")
    settings_block = data.get("post_settings", "")
    await callback.answer()
    thinking = await callback.message.answer("⏳ Пишу другой вариант…")
    try:
        draft = await claude.write_draft_from_plan(topic, hook, plan, style=style, settings=settings_block)
    except Exception as e:
        logger.error("Claude error: %s", e)
        await thinking.edit_text("Ошибка. Попробуй позже.")
        return
    await state.update_data(post_draft=draft)
    await _safe_delete(thinking)
    await callback.message.answer("📝 <b>Другой вариант:</b>", parse_mode="HTML")
    await _send(callback.message, draft, reply_markup=post_draft_keyboard())


@router.callback_query(F.data == "post:edit_draft")
async def post_edit_draft_prompt(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(PostFlow.waiting_draft_edit)
    # Убираем кнопки с черновика, чтобы он не дублировался — текст остаётся виден
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    # Новое сообщение с запросом инструкции — черновик виден выше
    await callback.message.answer(
        "✏️ Напиши инструкцию — что доработать в черновике:",
        reply_markup=cancel_keyboard(),
    )


@router.message(PostFlow.waiting_draft_edit)
async def post_handle_draft_edit(message: Message, state: FSMContext):
    if _is_command(message):
        return
    if not await _check_limit(message, LIMIT_INSTRUCTIONS):
        return
    data = await state.get_data()
    draft = data.get("post_draft", "")
    style = data.get("post_style", "")
    settings_block = data.get("post_settings", "")
    await state.set_state(PostFlow.reviewing_draft)
    thinking = await message.answer("⏳ Дорабатываю…")
    try:
        new_draft = await claude.edit_draft(draft, message.text, style=style, settings=settings_block)
    except Exception as e:
        logger.error("Claude error: %s", e)
        await thinking.edit_text("Ошибка. Попробуй позже.")
        return
    await state.update_data(post_draft=new_draft)
    await _safe_delete(thinking)
    await message.answer("📝 <b>Доработанный вариант:</b>", parse_mode="HTML")
    await _send(message, new_draft, reply_markup=post_draft_keyboard())


@router.callback_query(F.data == "post:done")
async def post_done(callback: CallbackQuery, state: FSMContext):
    import re as _re_html
    data = await state.get_data()
    draft = data.get("post_draft", "")
    topic = data.get("post_topic", "")

    if not draft or not draft.strip():
        await callback.answer("⚠️ Черновик пустой — сессия устарела.", show_alert=True)
        await _safe_edit(callback.message, "Сессия устарела. Начни пост заново:", reply_markup=main_menu())
        return

    # Заголовок для списка — первая непустая строка поста без HTML-тегов
    first_line = _re_html.sub(r"<[^>]+>", "", draft.split("\n")[0]).strip()
    display_title = first_line[:60] or (topic[:60] if topic else "Без темы")

    # Удаляем черновик — пост готов
    draft_id = data.get("draft_id")
    if draft_id:
        delete_draft(callback.from_user.id, draft_id)
    # Сохраняем в готовые к публикации
    try:
        save_post(callback.from_user.id, display_title, draft)
    except Exception as e:
        logger.error("Ошибка сохранения готового поста: %s", e)
    # Отмечаем пост как завершённый
    mark_post_completed(callback.from_user.id)
    await state.update_data(
        post_topic=None, post_hooks_text=None, post_chosen_hook=None,
        post_plan=None, post_draft=None, draft_id=None,
    )
    await state.set_state(None)
    await callback.answer("✅ Готово!")
    await callback.message.answer("✅ <b>Пост сохранён и готов к публикации:</b>", parse_mode="HTML")
    await _send(callback.message, draft, reply_markup=main_menu())


# ── DRAFTS ───────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "action:drafts")
async def cb_drafts_list(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    drafts = load_drafts(callback.from_user.id)
    if not drafts:
        await _safe_edit(callback.message,
            "📂 <b>Черновики</b>\n\nПока пусто.\nНачни писать пост — он автоматически сохранится при выходе в меню.",
            parse_mode="HTML",
            reply_markup=main_menu(),
        )
        return
    await _safe_edit(callback.message,
        f"📂 <b>Черновики</b> ({len(drafts)}):",
        parse_mode="HTML",
        reply_markup=drafts_list_keyboard(drafts),
    )


@router.callback_query(F.data.startswith("draft:open:"))
async def cb_draft_open(callback: CallbackQuery, state: FSMContext):
    draft_id = callback.data.split(":", 2)[2]
    draft = load_draft(callback.from_user.id, draft_id)
    await callback.answer()
    if not draft:
        await _safe_edit(callback.message,
            "❌ Черновик не найден.", reply_markup=main_menu()
        )
        return
    from datetime import datetime
    dt = datetime.fromisoformat(draft["saved_at"]).strftime("%d.%m %H:%M")
    topic = draft.get("topic", "Без темы")
    stage_label = draft.get("stage_label", "")
    await _safe_edit(callback.message,
        f"📄 <b>{topic}</b>\n"
        f"Стадия: {stage_label} · Сохранён: {dt}",
        parse_mode="HTML",
        reply_markup=draft_item_keyboard(draft_id),
    )


@router.callback_query(F.data.startswith("draft:resume:"))
async def cb_draft_resume(callback: CallbackQuery, state: FSMContext):
    draft_id = callback.data.split(":", 2)[2]
    draft = load_draft(callback.from_user.id, draft_id)
    await callback.answer()
    if not draft:
        await _safe_edit(callback.message, "❌ Черновик не найден.", reply_markup=main_menu())
        return
    # Загружаем все post_* поля обратно в FSM
    style = load_style_for_user(callback.from_user.id)
    settings_block = format_for_prompt(load_settings(callback.from_user.id))
    await state.update_data(**{k: v for k, v in draft.items() if k.startswith("post_")})
    await state.update_data(
        draft_id=draft_id, post_style=style, post_settings=settings_block,
    )
    # Убираем кнопки со старого сообщения, чтобы избежать повторного нажатия
    await _safe_edit(
        callback.message,
        f"▶️ Продолжаем: <b>{draft.get('topic', 'черновик')}</b>",
        parse_mode="HTML",
    )
    await _resume_post(callback.message, state, draft)


@router.callback_query(F.data.startswith("draft:delete:"))
async def cb_draft_delete(callback: CallbackQuery, state: FSMContext):
    draft_id = callback.data.split(":", 2)[2]
    deleted = delete_draft(callback.from_user.id, draft_id)
    await callback.answer("🗑 Удалено" if deleted else "Не найден")
    # Показываем обновлённый список
    drafts = load_drafts(callback.from_user.id)
    if not drafts:
        await _safe_edit(callback.message,
            "📂 <b>Черновики</b>\n\nВсе черновики удалены.",
            parse_mode="HTML",
            reply_markup=main_menu(),
        )
    else:
        await _safe_edit(callback.message,
            f"📂 <b>Черновики</b> ({len(drafts)}):",
            parse_mode="HTML",
            reply_markup=drafts_list_keyboard(drafts),
        )


# ── READY POSTS ──────────────────────────────────────────────────────────────

@router.callback_query(F.data == "action:ready_posts")
async def cb_ready_posts_list(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    posts = load_posts(callback.from_user.id)
    if not posts:
        await _safe_edit(
            callback.message,
            "📬 <b>Готовые посты</b>\n\nПока пусто.\nГотовые посты появятся здесь после нажатия «✅ Готово».",
            parse_mode="HTML",
            reply_markup=main_menu(),
        )
        return
    await _safe_edit(
        callback.message,
        f"📬 <b>Готовые посты</b> ({len(posts)}):",
        parse_mode="HTML",
        reply_markup=ready_posts_list_keyboard(posts),
    )


@router.callback_query(F.data.startswith("rpost:open:"))
async def cb_ready_post_open(callback: CallbackQuery, state: FSMContext):
    post_id = callback.data.split(":", 2)[2]
    post = load_post(callback.from_user.id, post_id)
    await callback.answer()
    if not post:
        await _safe_edit(callback.message, "❌ Пост не найден.", reply_markup=main_menu())
        return
    from datetime import datetime
    dt = datetime.fromisoformat(post["saved_at"]).strftime("%d.%m.%Y %H:%M")
    topic = post.get("topic", "Без темы")
    text = post.get("text", "")
    # Показываем заголовок с датой, потом сам текст поста
    await _safe_edit(
        callback.message,
        f"📬 <b>{topic}</b>\n<i>Сохранён: {dt}</i>",
        parse_mode="HTML",
        reply_markup=ready_post_item_keyboard(post_id),
    )
    if text and text.strip():
        await _send(callback.message, text, parse_mode="HTML")
    else:
        await callback.message.answer("⚠️ Текст поста не сохранился.")


@router.callback_query(F.data.startswith("rpost:delete:"))
async def cb_ready_post_delete(callback: CallbackQuery, state: FSMContext):
    post_id = callback.data.split(":", 2)[2]
    deleted = delete_post(callback.from_user.id, post_id)
    await callback.answer("🗑 Удалено" if deleted else "Не найден")
    posts = load_posts(callback.from_user.id)
    if not posts:
        await _safe_edit(
            callback.message,
            "📬 <b>Готовые посты</b>\n\nВсе посты удалены.",
            parse_mode="HTML",
            reply_markup=main_menu(),
        )
    else:
        await _safe_edit(
            callback.message,
            f"📬 <b>Готовые посты</b> ({len(posts)}):",
            parse_mode="HTML",
            reply_markup=ready_posts_list_keyboard(posts),
        )


# ── SETTINGS ──────────────────────────────────────────────────────────────────

def _settings_text() -> str:
    return (
        "⚙️ <b>Настройки тона поста</b>\n\n"
        "Нажми параметр чтобы изменить. Применяются ко всем новым постам.\n"
        "<i>🔗 Источники пока в режиме «софт» — реальные ссылки подключим позже.</i>"
    )


@router.callback_query(F.data == "action:settings")
async def cb_settings_open(callback: CallbackQuery, state: FSMContext):
    settings = load_settings(callback.from_user.id)
    await callback.answer()
    await _safe_edit(
        callback.message,
        _settings_text(),
        parse_mode="HTML",
        reply_markup=settings_main_keyboard(settings),
    )


@router.callback_query(F.data == "set:back")
async def cb_settings_back(callback: CallbackQuery, state: FSMContext):
    await state.set_state(None)
    settings = load_settings(callback.from_user.id)
    await callback.answer()
    await _safe_edit(
        callback.message,
        _settings_text(),
        parse_mode="HTML",
        reply_markup=settings_main_keyboard(settings),
    )


@router.callback_query(F.data == "set:channel")
async def cb_set_channel_prompt(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    current = get_channel(callback.from_user.id)
    current_text = f"Сейчас: <code>{current}</code>\n\n" if current else ""
    await _safe_edit(
        callback.message,
        f"📡 <b>Мой канал</b>\n\n{current_text}"
        "Введи @username своего канала:\n"
        "(или нажми Назад если не хочешь менять)",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="◀️ Назад", callback_data="set:back")
        ]]),
    )
    await state.set_state(ChannelFlow.waiting_for_channel)


@router.message(ChannelFlow.waiting_for_channel)
async def handle_set_channel(message: Message, state: FSMContext):
    if _is_command(message):
        return
    channel = message.text.strip()
    if not channel.startswith("@"):
        channel = "@" + channel
    set_channel(message.from_user.id, channel)
    await state.set_state(None)
    await message.answer(
        f"✅ Канал сохранён: <code>{channel}</code>\n\n"
        "Теперь можешь запустить анализ стиля через 🎨 Анализ стиля.",
        parse_mode="HTML",
        reply_markup=main_menu(),
    )


@router.callback_query(F.data.startswith("set:param:"))
async def cb_settings_param(callback: CallbackQuery, state: FSMContext):
    """Открывает экран регулировки параметра."""
    param = callback.data.split(":", 2)[2]
    settings = load_settings(callback.from_user.id)
    await callback.answer()

    if param == "length":
        current = settings.get("length", "medium")
        await _safe_edit(
            callback.message,
            f"📏 <b>Длина поста</b>\n\nСейчас: <b>{LENGTH_LABELS[current]}</b>",
            parse_mode="HTML",
            reply_markup=settings_length_keyboard(current),
        )
        return

    if param not in PARAM_LABELS:
        return

    value = int(settings.get(param, 0))
    label = PARAM_LABELS[param]
    await _safe_edit(
        callback.message,
        f"{label}: <b>{value}%</b>\n\n"
        "0 — минимум, 100 — максимум.\n"
        "Используй кнопки для точной регулировки.",
        parse_mode="HTML",
        reply_markup=settings_param_keyboard(param, value),
    )


@router.callback_query(F.data.startswith("set:adj:"))
async def cb_settings_adjust(callback: CallbackQuery, state: FSMContext):
    """Инкремент/декремент: set:adj:<param>:<delta>"""
    _, _, param, delta_str = callback.data.split(":", 3)
    settings = load_settings(callback.from_user.id)
    current = int(settings.get(param, 0))
    new_value = max(0, min(100, current + int(delta_str)))
    settings = update_param(callback.from_user.id, param, new_value)
    await callback.answer(f"{PARAM_LABELS[param]}: {new_value}%")
    label = PARAM_LABELS[param]
    await _safe_edit(
        callback.message,
        f"{label}: <b>{new_value}%</b>\n\n"
        "0 — минимум, 100 — максимум.\n"
        "Используй кнопки для точной регулировки.",
        parse_mode="HTML",
        reply_markup=settings_param_keyboard(param, new_value),
    )


@router.callback_query(F.data.startswith("set:val:"))
async def cb_settings_value(callback: CallbackQuery, state: FSMContext):
    """Точное значение по пресету: set:val:<param>:<value>"""
    _, _, param, value_str = callback.data.split(":", 3)
    new_value = int(value_str)
    settings = update_param(callback.from_user.id, param, new_value)
    await callback.answer(f"{PARAM_LABELS[param]}: {new_value}%")
    label = PARAM_LABELS[param]
    await _safe_edit(
        callback.message,
        f"{label}: <b>{new_value}%</b>\n\n"
        "0 — минимум, 100 — максимум.\n"
        "Используй кнопки для точной регулировки.",
        parse_mode="HTML",
        reply_markup=settings_param_keyboard(param, new_value),
    )


@router.callback_query(F.data.startswith("set:len:"))
async def cb_settings_length(callback: CallbackQuery, state: FSMContext):
    """Выбор длины: set:len:<short|medium|long>"""
    value = callback.data.split(":", 2)[2]
    update_param(callback.from_user.id, "length", value)
    await callback.answer(f"Длина: {LENGTH_LABELS.get(value, value)}")
    await _safe_edit(
        callback.message,
        f"📏 <b>Длина поста</b>\n\nСейчас: <b>{LENGTH_LABELS[value]}</b>",
        parse_mode="HTML",
        reply_markup=settings_length_keyboard(value),
    )


@router.callback_query(F.data == "set:reset")
async def cb_settings_reset(callback: CallbackQuery, state: FSMContext):
    settings = reset_settings(callback.from_user.id)
    await callback.answer("🔄 Сброшено к дефолтам")
    await _safe_edit(
        callback.message,
        _settings_text(),
        parse_mode="HTML",
        reply_markup=settings_main_keyboard(settings),
    )


# ── PAYMENTS ──────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "action:buy")
async def cb_buy(callback: CallbackQuery, state: FSMContext):
    balance = get_balance(callback.from_user.id)
    await callback.answer()
    await _safe_edit(
        callback.message,
        f"💳 <b>Пополнение баланса</b>\n\nТекущий баланс: <b>{balance} кредитов</b>\n\n"
        "Выбери способ оплаты:",
        parse_mode="HTML",
        reply_markup=buy_keyboard(),
    )


@router.callback_query(F.data == "buy:method:stars")
async def cb_buy_method_stars(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await _safe_edit(
        callback.message,
        "⭐ <b>Оплата Telegram Stars</b>\n\nВыбери пакет:",
        parse_mode="HTML",
        reply_markup=buy_stars_keyboard(),
    )


@router.callback_query(F.data == "buy:method:rub")
async def cb_buy_method_rub(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await _safe_edit(
        callback.message,
        "💳 <b>Оплата картой (ЮКасса)</b>\n\nВыбери пакет:",
        parse_mode="HTML",
        reply_markup=buy_rub_keyboard(),
    )


@router.callback_query(F.data.startswith("buy:stars:"))
async def cb_buy_stars_package(callback: CallbackQuery, state: FSMContext):
    from users_store import PACKAGES
    pkg_id = callback.data.split(":", 2)[2]
    if pkg_id not in PACKAGES:
        await callback.answer("Пакет не найден", show_alert=True)
        return
    pkg = PACKAGES[pkg_id]
    await callback.answer()
    await callback.message.answer_invoice(
        title="Кредиты для постов",
        description=pkg["label"],
        payload=f"credits_{pkg_id}_{callback.from_user.id}_stars",
        currency="XTR",
        prices=make_stars_prices(pkg_id),
    )


@router.callback_query(F.data.startswith("buy:rub:"))
async def cb_buy_rub_package(callback: CallbackQuery, state: FSMContext):
    from users_store import PACKAGES
    provider_token = _os.getenv("YUKASSA_PROVIDER_TOKEN", "")
    if not provider_token:
        await callback.answer("Оплата картой временно недоступна", show_alert=True)
        return
    pkg_id = callback.data.split(":", 2)[2]
    if pkg_id not in PACKAGES:
        await callback.answer("Пакет не найден", show_alert=True)
        return
    pkg = PACKAGES[pkg_id]
    await callback.answer()
    await callback.message.answer_invoice(
        title="Кредиты для постов",
        description=pkg["label"],
        payload=f"credits_{pkg_id}_{callback.from_user.id}_rub",
        provider_token=provider_token,
        currency="RUB",
        prices=make_rub_prices(pkg_id),
    )


@router.pre_checkout_query()
async def pre_checkout(query):
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def handle_payment(message: Message, state: FSMContext):
    from users_store import PACKAGES as PKG
    payload = message.successful_payment.invoice_payload
    # payload = "credits_{pkg_id}_{user_id}_{method}"
    parts = payload.split("_")
    pkg_id = parts[1] if len(parts) >= 2 else "starter"
    method = parts[3] if len(parts) >= 4 else "stars"
    pkg = PKG.get(pkg_id, PKG["starter"])

    currency = message.successful_payment.currency
    total = message.successful_payment.total_amount
    if currency == "XTR":
        paid_usd = total * 0.013 * 0.7   # Stars: ~$0.013 за звезду, минус 30% Telegram
    else:
        paid_usd = (total / 100) / 90 * 0.94  # RUB→USD, минус ~6% ЮКасса
    new_balance = add_credits(message.from_user.id, pkg["credits"], paid_usd)

    method_str = "⭐ Telegram Stars" if currency == "XTR" else "💳 Картой"
    await message.answer(
        f"✅ <b>Оплата прошла!</b>\n\n"
        f"Способ: {method_str}\n"
        f"Начислено: <b>{pkg['credits']} кредитов</b>\n"
        f"Новый баланс: <b>{new_balance} кредитов</b>\n\n"
        "Продолжай создавать посты 🚀",
        parse_mode="HTML",
        reply_markup=main_menu(),
    )


# ── ADMIN ─────────────────────────────────────────────────────────────────────

@router.message(Command("admin_stats"))
async def cmd_admin_stats(message: Message, state: FSMContext):
    admin_id = int(_os.getenv("ADMIN_ID", "0"))
    if message.from_user.id != admin_id:
        return
    from users_store import all_users
    users = all_users()
    total_cost = sum(u.get("total_cost_usd", 0) for u in users)
    total_paid = sum(u.get("total_paid_usd", 0) for u in users)
    total_posts = sum(u.get("total_posts", 0) for u in users)
    active = sum(1 for u in users if u.get("total_posts", 0) > 0)
    await message.answer(
        f"📊 <b>Статистика сервиса</b>\n\n"
        f"Пользователей: <b>{len(users)}</b> (активных: {active})\n"
        f"Постов создано: <b>{total_posts}</b>\n"
        f"Затрачено API: <b>${total_cost:.2f}</b>\n"
        f"Выручка: <b>${total_paid:.2f}</b>\n"
        f"Маржа: <b>{((total_paid - total_cost) / total_paid * 100):.0f}%</b>" if total_paid > 0 else
        f"📊 <b>Статистика</b>\n\nПользователей: {len(users)}\nПостов: {total_posts}\nAPI стоимость: ${total_cost:.2f}",
        parse_mode="HTML",
    )


@router.message(Command("admin_topup"))
async def cmd_admin_topup(message: Message, state: FSMContext):
    admin_id = int(_os.getenv("ADMIN_ID", "0"))
    if message.from_user.id != admin_id:
        return
    parts = message.text.split()
    if len(parts) < 3:
        await message.answer("Использование: /admin_topup <user_id> <credits>")
        return
    try:
        target_id = int(parts[1])
        amount = int(parts[2])
    except ValueError:
        await message.answer("Неверный формат.")
        return
    new_balance = add_credits(target_id, amount)
    await message.answer(f"✅ Начислено {amount} кредитов пользователю {target_id}. Баланс: {new_balance}")


@router.message(Command("balance"))
async def cmd_balance(message: Message, state: FSMContext):
    user = get_user(message.from_user.id)
    balance = user.get("credits", 0)
    total_posts = user.get("total_posts", 0)
    channel = user.get("channel", "") or "не задан"
    free = "✅ доступен" if is_first_post_free(message.from_user.id) else "использован"
    await message.answer(
        f"💳 <b>Мой баланс</b>\n\n"
        f"Кредиты: <b>{balance}</b>\n"
        f"Постов создано: <b>{total_posts}</b>\n"
        f"Бесплатный пост: {free}\n"
        f"Мой канал: <code>{channel}</code>",
        parse_mode="HTML",
        reply_markup=buy_keyboard() if balance < 10 else main_menu(),
    )


# ── FREE CHAT ─────────────────────────────────────────────────────────────────

@router.message(StateFilter(None))
async def free_chat(message: Message, state: FSMContext):
    if not message.text:
        return
    if len(message.text) < 2:
        await message.answer("Выбери действие из меню:", reply_markup=main_menu())
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
