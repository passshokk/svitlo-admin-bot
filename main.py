import os
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.client.default import DefaultBotProperties
from handlers import router
from middleware import LoadDataMiddleware

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не знайдено у змінних середовища!")

# 1. Створюємо персистентний Event Loop, який переживе окремі HTTP-запити
try:
    loop = asyncio.get_event_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

# 2. Глобальні інстанси ініціалізуються один раз і прив'язуються до вічного loop
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(
            parse_mode="HTML"
        )
    )
dp = Dispatcher()
dp.update.outer_middleware(LoadDataMiddleware())
dp.include_router(router)

async def process_update(request_json):
    update = types.Update(**request_json)
    await dp.feed_update(bot, update)

def telegram_webhook(request):
    if request.method != "POST":
        return "Method Not Allowed", 405
        
    request_json = request.get_json(silent=True)
    if request_json:
        # КРИТИЧНО: run_until_complete виконує таску, але залишає loop відкритим для Warm Starts
        loop.run_until_complete(process_update(request_json))
        
    return "OK", 200