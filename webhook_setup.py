# webhook_setup.py
import asyncio
import os
import logging
from aiogram import Bot
from dotenv import load_dotenv

# Завантажуємо змінні середовища для локального запуску
load_dotenv()

async def main():
    logging.basicConfig(level=logging.INFO)
    
    bot_token = os.getenv("BOT_TOKEN")
    service_url = os.getenv("SERVICE_URL")
    webhook_secret = os.getenv("WEBHOOK_SECRET")

    if not all([bot_token, service_url, webhook_secret]):
        raise ValueError("Відсутні необхідні змінні середовища (BOT_TOKEN, SERVICE_URL, WEBHOOK_SECRET)")

    bot = Bot(token=bot_token)
    
    # Формуємо URL ендпоінту (має збігатися з роутом @app.post("/") у main.py)
    webhook_url = f"{service_url.rstrip('/')}/"

    try:
        # Встановлюємо вебхук із жорсткою фільтрацією апдейтів
        await bot.set_webhook(
            url=webhook_url,
            secret_token=webhook_secret,
            allowed_updates=["message", "callback_query"], # Відрізає спам-івенти (edited_message, chat_member тощо)
            drop_pending_updates=True # Очищає чергу старих апдейтів, щоб бот не спамив після простою
        )
        
        info = await bot.get_webhook_info()
        logging.info(f"✅ Вебхук успішно встановлено: {info.url}")
        logging.info(f"✅ Дозволені апдейти: {info.allowed_updates}")
        
    except Exception as e:
        logging.error(f"❌ Помилка встановлення вебхука: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())