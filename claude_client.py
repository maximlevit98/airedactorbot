import json
import logging
import os
import anthropic
from dotenv import load_dotenv

logger = logging.getLogger(__name__)


def _log_usage(method: str, response) -> None:
    """Логирует использование токенов после каждого запроса к API."""
    u = response.usage
    cached = getattr(u, "cache_read_input_tokens", 0) or 0
    fresh_input = u.input_tokens - cached
    logger.info(
        "[tokens] %s → вход: %d (кэш: %d) | выход: %d",
        method, u.input_tokens, cached, u.output_tokens,
    )


def _extract_json(raw: str) -> dict:
    """
    Надёжно извлекает JSON из ответа Claude.
    Обрабатывает: чистый JSON, ```json...```, текст до/после JSON.
    """
    text = raw.strip()
    # Убираем markdown-обёртку
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        text = text.rsplit("```", 1)[0].strip()
    # Вырезаем между первой { и последней }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start:end + 1]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.error("Не удалось распарсить JSON. Ответ:\n%s", raw[:500])
        return {"raw": raw, "error": True}

load_dotenv(override=True)

EDITOR_SYSTEM_PROMPT = """Ты — главный редактор Telegram-канала про дизайн и личную жизнь автора.

Голос канала:
- Живой, личный, неформальный — как разговор с умным другом
- Конкретные детали и личный опыт вместо абстракций
- Ёмко: одна мысль — один пост, без воды
- Эмодзи умеренно, только когда усиливают смысл
- Вопросы к читателю в конце поощряются

Форматирование Telegram (HTML):
- <b>жирный</b> для акцентов, <i>курсив</i> для интонации
- Списки с дефисом или эмодзи, не с точками
- Абзацы через пустую строку
- Длина поста 300–900 символов (если нет других указаний)

Никогда не добавляй пояснений типа «вот отредактированный вариант» — только готовый результат."""


class ClaudeEditor:
    def __init__(self):
        self._client = anthropic.AsyncAnthropic(
            api_key=os.getenv("ANTHROPIC_API_KEY")
        )

    def _system(self) -> list:
        """Кэшированный системный промпт — экономит токены при повторных запросах."""
        return [
            {
                "type": "text",
                "text": EDITOR_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ]

    async def analyze_style(self, posts: list[str]) -> dict:
        """Глубокий анализ стиля канала. Opus — задача одноразовая, результат кэшируется."""
        posts_text = "\n\n---\n\n".join(posts)
        response = await self._client.messages.create(
            model="claude-opus-4-6",
            max_tokens=2048,
            system=self._system(),
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Проанализируй стиль этих постов из Telegram-канала и составь детальный профиль.\n\n"
                        "Верни строго валидный JSON без markdown-обёртки со следующими полями:\n"
                        '- "tone": тон (разговорный/профессиональный/лирический и т.д.)\n'
                        '- "topics": список основных тем (массив строк)\n'
                        '- "avg_length": средняя длина (коротко/средне/длинно)\n'
                        '- "emoji_style": использование эмодзи (отсутствует/редко/умеренно/часто)\n'
                        '- "structure": типичная структура постов\n'
                        '- "vocabulary": характерные слова и обороты (массив)\n'
                        '- "hooks": как обычно начинаются посты\n'
                        '- "cta": типичные призывы к действию\n'
                        '- "summary": 2-3 предложения о голосе канала\n\n'
                        f"ПОСТЫ:\n{posts_text}"
                    ),
                }
            ],
        )
        _log_usage("analyze_style", response)
        return _extract_json(response.content[0].text)

    async def merge_style_analyses(self, analyses: list[dict]) -> dict:
        """Объединяет несколько частичных анализов в один итоговый профиль. Opus."""
        analyses_text = json.dumps(analyses, ensure_ascii=False, indent=2)
        response = await self._client.messages.create(
            model="claude-opus-4-6",
            max_tokens=4096,
            system=self._system(),
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Объедини несколько частичных анализов стиля одного канала в один итоговый профиль.\n\n"
                        "Верни строго валидный JSON без markdown-обёртки с теми же полями:\n"
                        '"tone", "topics", "avg_length", "emoji_style", "structure", '
                        '"vocabulary", "hooks", "cta", "summary"\n\n'
                        "Учти все части равномерно. В summary — финальный вывод о голосе канала.\n\n"
                        f"ЧАСТИ:\n{analyses_text}"
                    ),
                }
            ],
        )
        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1]
            raw = raw.rsplit("```", 1)[0].strip()
        _log_usage("merge_style_analyses", response)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"raw": raw, "error": True}

    async def generate_ideas(self, context: str, count: int = 7, style: str = "", settings: str = "") -> str:
        """Генерация идей для постов. Sonnet — основная рабочая задача."""
        style_block = f"\n\n{style}" if style else ""
        settings_block = f"\n\n{settings}" if settings else ""
        response = await self._client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=self._system(),
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Сгенерируй {count} идей для постов.\n\n"
                        f"Контекст: {context}"
                        f"{style_block}"
                        f"{settings_block}\n\n"
                        f"Для каждой идеи: заголовок (1 строка) + угол подачи (1–2 предложения).\n"
                        f"Нумеруй от 1 до {count}."
                    ),
                }
            ],
        )
        _log_usage("generate_ideas", response)
        return response.content[0].text

    async def create_plan(self, topic: str, style: str = "", settings: str = "") -> str:
        """Создать детальный план поста."""
        style_block = f"\n\n{style}" if style else ""
        settings_block = f"\n\n{settings}" if settings else ""
        response = await self._client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1200,
            system=self._system(),
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Составь план поста на тему:\n{topic}"
                        f"{style_block}"
                        f"{settings_block}\n\n"
                        "1. Хук — 1–2 предложения\n"
                        "2. Основная мысль\n"
                        "3. Структура — 3–5 блоков с тезисами\n"
                        "4. Детали и примеры\n"
                        "5. Финал / призыв к действию\n\n"
                        "Конкретно, без воды."
                    ),
                }
            ],
        )
        _log_usage("create_plan", response)
        return response.content[0].text

    async def edit_draft(self, draft: str, instructions: str, style: str = "", settings: str = "") -> str:
        """Редактировать черновик по инструкции автора."""
        style_block = f"\n\n{style}" if style else ""
        settings_block = f"\n\n{settings}" if settings else ""
        response = await self._client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=self._system(),
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Отредактируй черновик поста по инструкции."
                        f"{style_block}"
                        f"{settings_block}\n\n"
                        f"ИНСТРУКЦИЯ: {instructions}\n\n"
                        f"ЧЕРНОВИК:\n{draft}"
                    ),
                }
            ],
        )
        _log_usage("edit_draft", response)
        return response.content[0].text

    async def generate_hooks(self, topic: str, style: str = "", settings: str = "") -> str:
        """3 варианта хука (первой фразы) для поста."""
        style_block = f"\n\n{style}" if style else ""
        settings_block = f"\n\n{settings}" if settings else ""
        response = await self._client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=600,
            system=self._system(),
            messages=[{
                "role": "user",
                "content": (
                    f"Придумай 3 разных хука (первая фраза поста) на тему:\n{topic}"
                    f"{style_block}"
                    f"{settings_block}\n\n"
                    "Каждый хук — 1-2 предложения. Нумеруй: 1. 2. 3.\n"
                    "Подходы разные: эмоция, вопрос, провокация или факт."
                ),
            }],
        )
        _log_usage("generate_hooks", response)
        return response.content[0].text

    async def write_draft_from_plan(
        self, topic: str, hook: str, plan: str, style: str = "", settings: str = ""
    ) -> str:
        """Пишет готовый черновик по теме, хуку и плану."""
        style_block = f"\n\n{style}" if style else ""
        settings_block = f"\n\n{settings}" if settings else ""
        hook_block = f"\nХук (первая фраза): {hook}" if hook else ""
        response = await self._client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1200,
            system=self._system(),
            messages=[{
                "role": "user",
                "content": (
                    f"Напиши готовый пост по этим данным:\n"
                    f"Тема: {topic}"
                    f"{hook_block}\n"
                    f"План:\n{plan}"
                    f"{style_block}"
                    f"{settings_block}\n\n"
                    "Только текст поста, без пояснений."
                ),
            }],
        )
        _log_usage("write_draft_from_plan", response)
        return response.content[0].text

    async def quick_post(self, topic: str, style: str = "", settings: str = "") -> str:
        """Быстрый режим: тема → готовый пост за один шаг."""
        style_block = f"\n\n{style}" if style else ""
        settings_block = f"\n\n{settings}" if settings else ""
        response = await self._client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1200,
            system=self._system(),
            messages=[{
                "role": "user",
                "content": (
                    f"Напиши готовый пост на тему:\n{topic}"
                    f"{style_block}"
                    f"{settings_block}\n\n"
                    "Только текст поста, без пояснений."
                ),
            }],
        )
        _log_usage("quick_post", response)
        return response.content[0].text

    async def digest_channels(self, posts: list[str]) -> str:
        """Дайджест постов из смежных каналов. Haiku — быстрая дешёвая задача."""
        posts_text = "\n\n---\n\n".join(posts)
        response = await self._client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1200,
            system=self._system(),
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Дайджест постов из других каналов.\n\n"
                        "Для каждого: главная мысль (1 предложение) + можно ли использовать как идею.\n"
                        "Похожие темы группируй. Кратко.\n\n"
                        f"ПОСТЫ:\n{posts_text}"
                    ),
                }
            ],
        )
        _log_usage("digest_channels", response)
        return response.content[0].text

    async def chat(self, history: list[dict]) -> str:
        """Свободный диалог. Haiku — дешевле в 5× чем Sonnet, для чата достаточно."""
        response = await self._client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=self._system(),
            messages=history,
        )
        _log_usage("chat", response)
        return response.content[0].text
