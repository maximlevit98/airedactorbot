import json
import os
import anthropic
from dotenv import load_dotenv

load_dotenv()

EDITOR_SYSTEM_PROMPT = """Ты — главный редактор Telegram-канала про дизайн и личную жизнь автора.

Голос канала:
- Живой, личный, неформальный — как разговор с умным другом
- Конкретные детали и личный опыт вместо абстракций
- Ёмко: одна мысль — один пост, без воды
- Эмодзи умеренно, только когда усиливают смысл
- Вопросы к читателю в конце поощряются

Форматирование Telegram:
- **жирный** для акцентов, _курсив_ для интонации
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
        """Глубокий анализ стиля канала. Opus-4-6 — задача одноразовая и сложная."""
        posts_text = "\n\n---\n\n".join(posts)
        response = await self._client.messages.create(
            model="claude-opus-4-6",
            max_tokens=4096,
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
        raw = response.content[0].text.strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"raw": raw, "error": True}

    async def generate_ideas(self, context: str, count: int = 7) -> str:
        """Генерация идей для постов. Sonnet — основная рабочая задача."""
        response = await self._client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=self._system(),
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Сгенерируй {count} идей для постов в Telegram-канале про дизайн и личную жизнь.\n\n"
                        f"Контекст от автора: {context}\n\n"
                        f"Для каждой идеи:\n"
                        f"— Цепляющий заголовок/тему (1 строка)\n"
                        f"— Угол подачи: что именно интересного (1–2 предложения)\n\n"
                        f"Нумеруй от 1 до {count}."
                    ),
                }
            ],
        )
        return response.content[0].text

    async def create_plan(self, topic: str) -> str:
        """Создать детальный план поста."""
        response = await self._client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=self._system(),
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Составь детальный план поста для Telegram-канала на тему:\n{topic}\n\n"
                        "Структура плана:\n"
                        "1. Хук — первые 1–2 предложения, чтобы захотелось читать\n"
                        "2. Основная мысль — о чём пост\n"
                        "3. Структура — 3–5 блоков с тезисами\n"
                        "4. Детали и примеры для каждого блока\n"
                        "5. Финал / призыв к действию\n\n"
                        "Пиши конкретно — это рабочий план, не пересказ темы."
                    ),
                }
            ],
        )
        return response.content[0].text

    async def edit_draft(self, draft: str, instructions: str) -> str:
        """Редактировать черновик по инструкции автора."""
        response = await self._client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=self._system(),
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Отредактируй черновик поста по инструкции.\n\n"
                        f"ИНСТРУКЦИЯ: {instructions}\n\n"
                        f"ЧЕРНОВИК:\n{draft}"
                    ),
                }
            ],
        )
        return response.content[0].text

    async def digest_channels(self, posts: list[str]) -> str:
        """Дайджест постов из смежных каналов. Haiku — быстрая дешёвая задача."""
        posts_text = "\n\n---\n\n".join(posts)
        response = await self._client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2048,
            system=self._system(),
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Сделай краткий дайджест постов из смежных каналов.\n\n"
                        "Для каждого поста:\n"
                        "— Главная мысль (1 предложение)\n"
                        "— Может ли вдохновить на пост в нашем канале? Если да — как именно\n\n"
                        "Сгруппируй похожие темы. Будь лаконичен.\n\n"
                        f"ПОСТЫ:\n{posts_text}"
                    ),
                }
            ],
        )
        return response.content[0].text

    async def chat(self, message: str) -> str:
        """Свободный диалог с редактором."""
        response = await self._client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=self._system(),
            messages=[
                {
                    "role": "user",
                    "content": message,
                }
            ],
        )
        return response.content[0].text
