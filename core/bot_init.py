# bot_init.py
import os
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from bot.fsm_storage import FirestoreStorage

BOT_TOKEN = os.getenv("BOT_TOKEN")
# Секретний токен для валідації запитів від Telegram
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is missing in environment variables")

if not WEBHOOK_SECRET:
    raise ValueError("WEBHOOK_SECRET is missing in environment variables")

bot = Bot(
    token=BOT_TOKEN, 
    default=DefaultBotProperties(parse_mode="HTML")
)

dp = Dispatcher(storage=FirestoreStorage())