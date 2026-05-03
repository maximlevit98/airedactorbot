"""
Одноразовый скрипт авторизации Telethon.
Запусти один раз: python auth.py
После этого появится файл session.session — бот будет его использовать.
"""
import asyncio
import os
from dotenv import load_dotenv
from telethon import TelegramClient

load_dotenv()


async def main():
    api_id = os.getenv("TELEGRAM_API_ID", "")
    api_hash = os.getenv("TELEGRAM_API_HASH", "")

    if not api_id or not api_hash:
        print("❌ Добавь TELEGRAM_API_ID и TELEGRAM_API_HASH в .env")
        print("   Получить на https://my.telegram.org → API development tools")
        return

    client = TelegramClient("session", int(api_id), api_hash)
    await client.start()  # попросит номер телефона и код из Telegram
    me = await client.get_me()
    print(f"✅ Авторизован как {me.first_name} (@{me.username})")
    print("   Файл session.session сохранён — бот готов читать каналы.")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
