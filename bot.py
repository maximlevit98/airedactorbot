import asyncio
import logging
import os
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand
from dotenv import load_dotenv

from handlers import router
from init_data import restore as restore_data

load_dotenv(override=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BOT_COMMANDS = [
    BotCommand(command="start", description="Главное меню"),
    BotCommand(command="new_post", description="Написать новый пост"),
    BotCommand(command="ideas", description="Идеи для постов"),
    BotCommand(command="plan", description="План поста"),
    BotCommand(command="edit", description="Редактура черновика"),
    BotCommand(command="digest", description="Дайджест каналов"),
    BotCommand(command="style", description="Анализ стиля канала"),
    BotCommand(command="fetch_channel", description="Выгрузить посты из канала"),
    BotCommand(command="cancel", description="Отменить текущее действие"),
]


async def main():
    restore_data()  # восстанавливаем данные при первом старте

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN не задан в .env")

    bot = Bot(
        token=bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    await bot.set_my_commands(BOT_COMMANDS)
    logger.info("Бот запущен")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
