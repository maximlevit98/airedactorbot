import os
import anthropic
from dotenv import load_dotenv

load_dotenv()

SYSTEM_PROMPT = """Ты — профессиональный редактор Telegram-канала. Твоя задача — создавать и редактировать посты.

Правила:
- Пиши живо, ёмко, без воды
- Используй эмодзи умеренно и к месту
- Форматируй текст для Telegram: жирный **текст**, курсив _текст_, моноширинный `код`
- Длина поста — до 1000 символов, если не указано иное
- Избегай канцелярита и штампов
- Заканчивай призывом к действию или вопросом, если уместно

Возвращай ТОЛЬКО готовый текст поста без пояснений и комментариев."""


class ClaudeClient:
    def __init__(self):
        self._client = anthropic.AsyncAnthropic(
            api_key=os.getenv("ANTHROPIC_API_KEY")
        )

    async def edit_post(self, text: str) -> str:
        response = await self._client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[
                {
                    "role": "user",
                    "content": f"Отредактируй и улучши этот пост для Telegram-канала:\n\n{text}",
                }
            ],
        )
        return response.content[0].text

    async def generate_post(self, topic: str) -> str:
        response = await self._client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[
                {
                    "role": "user",
                    "content": f"Напиши пост для Telegram-канала на тему: {topic}",
                }
            ],
        )
        return response.content[0].text
