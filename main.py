# main.py
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response, Header, HTTPException
from aiogram import types
from aiogram.types import ErrorEvent

from core.bot_init import bot, dp, WEBHOOK_SECRET
from bot.handlers import tg_router
from api.task_routes import tasks_router
from bot.middleware import LoadDataMiddleware, TicketConflictNoticeMiddleware
from api.webapp_routes import webapp_router
from core import utils as ut
from core import schooltoday

# === БЛОК ЛОГУВАННЯ ===
# Залишаємо INFO як базовий рівень для кастомних логів
logging.basicConfig(level=logging.INFO)

# Глушимо спам від uvicorn (HTTP запити)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

# Глушимо спам від aiogram (Update is handled / is not handled)
logging.getLogger("aiogram.event").setLevel(logging.WARNING)
# ================================

# Реєструємо middlewares та хендлери для Telegram
dp.update.outer_middleware(LoadDataMiddleware())
dp.message.outer_middleware(TicketConflictNoticeMiddleware())
dp.include_router(tg_router)


@dp.errors()
async def handle_unexpected_error(event: ErrorEvent) -> bool:
    """Останній рубіж: якщо хендлер впав з необробленим виключенням (напр. тимчасовий збій Firestore),
    юзер все одно отримує відповідь замість мовчазного зависання посеред розмови/анкети."""
    exc = event.exception
    logging.error("Unhandled update error", exc_info=(type(exc), exc, exc.__traceback__))

    update = event.update
    chat = None
    if update.message:
        chat = update.message.chat
    elif update.callback_query and update.callback_query.message:
        chat = update.callback_query.message.chat

    if chat and chat.type == "private":
        try:
            await bot.send_message(
                chat.id,
                "⚠️ Сталася тимчасова технічна помилка. Спробуй, будь ласка, повторити останню дію — якщо не допоможе, напиши /help"
            )
        except Exception:
            pass

    return True


@asynccontextmanager
async def lifespan(app: FastAPI):
    await ut.setup_owner_commands(bot)
    logging.info("Svitlo Bot backend started")
    yield
    # Безпечне закриття сесії aiohttp при шатдауні контейнера
    await bot.session.close()
    # Пул з'єднань до SchoolToday живе весь час роботи процесу — закриваємо явно
    await schooltoday.close_client()
    logging.info("Svitlo Bot backend shutting down")


app = FastAPI(lifespan=lifespan)
# Монтуємо роутер Cloud Tasks (всі ендпоінти /tasks/*)
app.include_router(tasks_router)
# Монтуємо роутер WebApp (камера та ШІ)
app.include_router(webapp_router)

# Головний роут для вебхуків Telegram
@app.post("/")
async def telegram_webhook(
    request: Request,
    # FastAPI автоматично мапить Header "X-Telegram-Bot-Api-Secret-Token"
    x_telegram_bot_api_secret_token: str | None = Header(default=None) 
):
    # 1. Захист вебхука
    if x_telegram_bot_api_secret_token != WEBHOOK_SECRET:
        logging.warning("Unauthorized webhook access attempt")
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        update_data = await request.json()
        update = types.Update(**update_data)
        
        # 2. Обробка апдейту. 
        # Увага:  чекаємо завершення (await), щоб Cloud Run не заморозив CPU.
        # Важкі таски хендлер має відправляти в Cloud Tasks.
        await dp.feed_update(bot, update)
        
        return Response(status_code=200)
    except Exception:
        logging.exception("Webhook processing error")
        # Завжди повертаємо 200, щоб Telegram не спамив ретраями при 500-х помилках
        return Response(status_code=200)