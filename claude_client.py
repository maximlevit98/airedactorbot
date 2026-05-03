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
        """Глубокий анализ стиля канала."""
        posts_text = "\n\n---\n\n".join(posts)
        response = await self._client.messages.create(
            model="claude-sonnet-4-6",
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
        raw = response.content[0].text.strip()
        # Claude иногда оборачивает JSON в ```json...``` несмотря на инструкцию
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1]
            raw = raw.rsplit("```", 1)[0].strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"raw": raw, "error": True}

    async def generate_ideas(self, context: str, count: int = 7) -> str:
        """Генерация идей для постов. Sonnet — основная рабочая задача."""
        response = await self._client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=self._system(),
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Сгенерируй {count} идей для постов.\n\n"
                        f"Контекст: {context}\n\n"
                        f"Для каждой идеи: заголовок (1 строка) + угол подачи (1–2 предложения).\n"
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
            max_tokens=1200,
            system=self._system(),
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Составь план поста на тему:\n{topic}\n\n"
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
        return response.content[0].text

    async def edit_draft(self, draft: str, instructions: str) -> str:
        """Редактировать черновик по инструкции автора."""
        response = await self._client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
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
        return response.content[0].text

    async def chat(self, history: list[dict]) -> str:
        """Свободный диалог. Haiku — дешевле в 5× чем Sonnet, для чата достаточно."""
        response = await self._client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=self._system(),
            messages=history,
        )
        return response.content[0].text
