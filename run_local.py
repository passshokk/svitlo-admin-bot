import os
import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from handlers import router
from middleware import LoadDataMiddleware
from dotenv import load_dotenv

load_dotenv()

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
    
    dp.include_router(router)
    
    print("🤖 Бот запущено локально!")
    
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())