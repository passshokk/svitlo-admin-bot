# task_routes.py
import logging
from fastapi import APIRouter, Request, Response
import core.database as db
import core.config as cfg
from core.bot_init import bot

tasks_router = APIRouter(prefix="/tasks")

@tasks_router.post("/sla_check")
async def task_sla_check(request: Request):
    """
    Воркер Cloud Tasks: перевіряє статус тікета через 10 хвилин.
    """
    try:
        payload = await request.json()
        ticket_id = payload.get("ticket_id")
        category = payload.get("category", "Невідомо")
        
        if not ticket_id:
            return Response(status_code=400)

        ticket_data = await db.get_ticket(ticket_id)
        
        if ticket_data and ticket_data.get('status') == 'open':
            await bot.send_message(
                chat_id=cfg.CURATOR_GROUP_ID,
                text=(
                    f"<b>🚨 {cfg.MAIN_CURATOR_USERNAME} 🚨</b>\n"
                    f"Тікет <code>#{ticket_id:05}</code> [Категорія: {category}] висить 10 хв без відповіді!"
                ),
                parse_mode="HTML",
                reply_to_message_id=int(ticket_id)
            )
            
        return Response(status_code=200)

    except Exception as e:
        logging.error(f"SLA Task error: {e}")
        # Повертаємо 500, щоб Cloud Tasks спробував виконати запит повторно (Retry Policy)
        return Response(status_code=500)