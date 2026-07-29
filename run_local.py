import os
import asyncio
import logging
from dotenv import load_dotenv

load_dotenv()

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from bot.handlers import tg_router
from bot.middleware import LoadDataMiddleware
from core import utils as ut

async def main():
    logging.basicConfig(level=logging.INFO)
    
    token = os.getenv("TEST_BOT_TOKEN")
    if not token:
        raise ValueError("TEST_BOT_TOKEN не знайдено! Перевір файл .env")

    bot = Bot(
        token=token,
        default=DefaultBotProperties(
            parse_mode="HTML"
        )
    )
    
    dp = Dispatcher()
    dp.update.outer_middleware(LoadDataMiddleware())
    
    dp.include_router(tg_router)

    await ut.setup_owner_commands(bot)
    print("🤖 Бот запущено локально!")
    
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())