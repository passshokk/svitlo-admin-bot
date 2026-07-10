import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from aiogram import Bot, Dispatcher, types
from aiogram.client.default import DefaultBotProperties

from handlers import router
from middleware import LoadDataMiddleware
# TODO: from fsm_storage import FirestoreStorage (Додамо на етапi FSM)

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is missing in environment variables.")

bot = Bot(
    token=BOT_TOKEN, 
    default=DefaultBotProperties(parse_mode="HTML")
)

# TODO: dp = Dispatcher(storage=FirestoreStorage())
dp = Dispatcher() 
dp.update.outer_middleware(LoadDataMiddleware())
dp.include_router(router)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.info("Svitlo Bot backend started")
    yield
    logging.info("Svitlo Bot backend shutting down")

app = FastAPI(lifespan=lifespan)

# --- ROUTE 1: TELEGRAM WEBHOOK ---
@app.post("/")
async def telegram_webhook(request: Request):
    try:
        update_data = await request.json()
        update = types.Update(**update_data)
        await dp.feed_update(bot, update)
        return Response(status_code=200)
    except Exception as e:
        logging.error(f"Webhook processing error: {e}")
        return Response(status_code=200)

# --- ROUTE 2: CLOUD TASKS (AI VALIDATION) ---
@app.post("/tasks/ai_validation")
async def task_ai_validation(request: Request):
    # Тут буде логіка валідації OIDC токена та виклик OpenAI
    return Response(status_code=200)

# --- ROUTE 3: CLOUD TASKS (SLA TIMER) ---
@app.post("/tasks/sla_check")
async def task_sla_check(request: Request):
    # Тут буде логіка перевірки статусу тікета з Firestore
    return Response(status_code=200)