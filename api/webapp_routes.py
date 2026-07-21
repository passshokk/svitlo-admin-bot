# api/webapp_routes.py
import os
import hmac
import hashlib
import json
import base64
import re
from urllib.parse import parse_qsl
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import vertexai
from vertexai.generative_models import GenerativeModel, Part
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from bot import keyboards as kb
from core import database as db
from core.bot_init import bot
from core import config as cfg

webapp_router = APIRouter()
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Ініціалізація Vertex AI (бере credentials з сервіс-акаунта Cloud Run)
vertexai.init(project="svitlo-auth-bot", location="us-central1")
vision_model = GenerativeModel("gemini-1.5-flash-001")

class VisionPayload(BaseModel):
    image_base64: str
    init_data: str

def validate_tg_init_data(init_data: str, token: str) -> bool:
    if not init_data:
        return False
    try:
        parsed_data = dict(parse_qsl(init_data))
        if "hash" not in parsed_data:
            return False
        received_hash = parsed_data.pop("hash")
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed_data.items()))
        secret_key = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
        calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        return calculated_hash == received_hash
    except Exception:
        return False

@webapp_router.get("/webapp/camera", response_class=HTMLResponse)
async def get_scanner_ui():
    html_path = Path(__file__).parent / "scanner.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))

@webapp_router.post("/api/vision")
async def process_vision(payload: VisionPayload):
    # 1. Валідація запиту
    if not validate_tg_init_data(payload.init_data, BOT_TOKEN):
        raise HTTPException(status_code=403, detail="Invalid InitData")
    
    try:
        parsed_data = dict(parse_qsl(payload.init_data))
        user_data = json.loads(parsed_data['user'])
        user_id = user_data['id']
    except Exception:
        raise HTTPException(status_code=400, detail="Cannot parse user payload")

    # 2. Підготовка зображення для Gemini
    try:
        base64_str = payload.image_base64.split(",")[1]
        image_bytes = base64.b64decode(base64_str)
        image_part = Part.from_data(data=image_bytes, mime_type="image/jpeg")
        
        prompt = """Аналізуй цей документ. Поверни суворий JSON:
        {"is_ua_document": true/false, "doc_type": "id_card/international_passport/birth_certificate/other", "confidence": 0.0-1.0}
        Шукай українські маркери (Тризуб, написи 'Україна', 'Ukraine')."""
        
        response = await vision_model.generate_content_async(
            [image_part, prompt],
            generation_config={"response_mime_type": "application/json"}
        )
        # ДОДАНО: Очищення можливого маркдауну перед парсингом
        clean_json = re.sub(r'^```json\s*|\s*```$', '', response.text.strip(), flags=re.IGNORECASE)
        result = json.loads(clean_json)
        
        # 3. Маршрутизація результату
        if result.get("is_ua_document") and result.get("confidence", 0) > 0.6:
            student = await db.get_student_by_tg_id(user_id)
            if not student:
                return {"success": False, "error": "Профіль не знайдено"}
            
            doc_id = student['id']
            student_data = student['data']
            
            # Оновлюємо Flat Schema
            await db.db.collection('Svitlo').document(doc_id).update({
                "ai_doc_valid": True,
                "ai_doc_type": result.get("doc_type", "unknown"),
                "crm_stage": "admin_review",
                "crm_stage_updated_at": db.get_kyivtime_now()
            })
            
            # Server-Side Push: Сповіщаємо юзера про успіх
            await bot.send_message(
                chat_id=user_id,
                text="✅ <b>Документ успішно розпізнано!</b>\nТвоя заявка передана кураторам на фінальне затвердження. Очікуй на повідомлення",
                parse_mode="HTML"
            )
            
            # ФОРМУВАННЯ КАРТКИ КУРАТОРА            
            tg_username = student_data.get('telegramUsername', '').replace('@', '')
            keyboard = kb.get_admin_action_kb(doc_id, tg_username, include_details_btn=True)
            
            full_name = f"{student_data.get('name', '')} {student_data.get('surname', '')}"
            age_group = "Older (14-18)" if student_data.get('ageGroup') == "older" else "Younger (10-13)"
            phone = student_data.get('phone', 'Не вказано')
            display_username = f"@{tg_username}" if tg_username else "Без юзернейму"

            await bot.send_message(
                chat_id=cfg.ADMIN_GROUP_ID,
                text=(
                    f"<b>🆕 Нова заявка на верифікацію!</b>\n\n"
                    f"<b>Студент:</b> {full_name}\n"
                    f"<b>Група:</b> {age_group}\n"
                    f"<b>Контакти:</b> <code>{phone}</code> | {display_username}\n"
                    f"<b>ШІ розпізнав:</b> {result.get('doc_type')} (Точність: {int(result.get('confidence', 0)*100)}%)\n\n"
                    f"Очікує рішення куратора."
                ),
                parse_mode="HTML",
                reply_markup=keyboard
            )
            
            return {"success": True}
        else:
            return {"success": False, "error": "Не знайдено українських маркерів. Переконайся, що документ добре видно у кадрі, та спробуй ще раз"}
            
    except Exception as e:
        import logging
        logging.error(f"Vertex AI Vision Error: {e}")
        return {"success": False, "error": "Помилка обробки ШІ. Спробуй пізніше."}