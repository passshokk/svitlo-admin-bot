# api/webapp_routes.py
import os
import hmac
import hashlib
import json
import base64
import re
from urllib.parse import parse_qsl
from pathlib import Path
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import vertexai
from vertexai.generative_models import GenerativeModel, Part
import logging
import httpx

from bot import keyboards as kb
from core import database as db
from core.database import db as firestore_client
from core.bot_init import bot
from core import config as cfg
from core.constants import APPLICATION_RECEIVED_MSG

# Приховає рівень WARNING від внутрішніх логерів Vertex AI
logging.getLogger("root").setLevel(logging.ERROR)

webapp_router = APIRouter()
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Ініціалізація Vertex AI (бере credentials з сервіс-акаунта Cloud Run)
vertexai.init(project="svitlo-auth-bot", location="global")
vision_model = GenerativeModel("gemini-3.5-flash-lite")

BLOCKED_TIMEZONES = {
    "Europe/Moscow", "Europe/Samara", "Asia/Yekaterinburg", 
    "Europe/Volgograd", "Asia/Omsk", "Asia/Novosibirsk", 
    "Asia/Krasnoyarsk", "Asia/Irkutsk", "Asia/Yakutsk", 
    "Asia/Vladivostok", "Asia/Magadan", "Asia/Kamchatka", "Asia/Anadyr"
}

class VisionPayload(BaseModel):
    image_base64: str
    init_data: str
    timezone: str | None = None

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

async def is_russian_ip(ip: str) -> bool:
    """Перевіряє через GeoIP API належність IP-адреси до РФ."""
    if ip in ("127.0.0.1", "localhost", "unknown"):
        return False
    try:
        async with httpx.AsyncClient(timeout=1.5) as client:
            resp = await client.get(f"http://ip-api.com/json/{ip}?fields=countryCode")
            if resp.status_code == 200:
                data = resp.json()
                return data.get("countryCode") == "RU"
    except Exception as e:
        logging.warning(f"GeoIP check failed for {ip}: {e}")
    return False

@webapp_router.get("/webapp/camera", response_class=HTMLResponse)
async def get_scanner_ui():
    html_path = Path(__file__).parent / "scanner.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))

@webapp_router.post("/api/vision")
async def process_vision(payload: VisionPayload, request: Request):
    # 1. Валідація Telegram init_data
    if not validate_tg_init_data(payload.init_data, BOT_TOKEN):
        raise HTTPException(status_code=403, detail="Invalid InitData")
    
    try:
        parsed_data = dict(parse_qsl(payload.init_data))
        user_data = json.loads(parsed_data['user'])
        user_id = user_data['id']
    except Exception:
        raise HTTPException(status_code=400, detail="Cannot parse user payload")

    # 2. Витягуємо IP-адресу клієнта з інфраструктури Cloud Run
    x_forwarded_for = request.headers.get("X-Forwarded-For")
    client_ip = x_forwarded_for.split(",")[0].strip() if x_forwarded_for else (request.client.host if request.client else "unknown")

    # 3. Перевірка 1: GeoIP
    if await is_russian_ip(client_ip):
        student = await db.get_student_by_tg_id(user_id)
        if student:
            await db.update_crm_stage(student['id'], "blocked")
            await db.clear_user_fsm(user_id)
        return {"success": False, "error": "Доступ обмежено за регіональними параметрами мережі."}

    # 4. Перевірка 2: Таймзона пристрою
    if payload.timezone in BLOCKED_TIMEZONES:
        student = await db.get_student_by_tg_id(user_id)
        if student:
            await db.update_crm_stage(student['id'], "blocked")
            await db.clear_user_fsm(user_id)
        return {"success": False, "error": "Регіональні параметри пристрою не підтримуються."}

    # 5. Перевірка 3: ШІ-аналіз документа через Gemini Vision
    try:
        base64_str = payload.image_base64.split(",")[1]
        image_bytes = base64.b64decode(base64_str)
        image_part = Part.from_data(data=image_bytes, mime_type="image/jpeg")
        
        prompt = """Аналізуй цей документ. Поверни суворий JSON:
        {
          "is_ua_document": true/false, 
          "doc_type": "id_card/international_passport/birth_certificate/other", 
          "has_russian_markers": true/false,
          "confidence": 0.0-1.0
        }
        Умови:
        1. is_ua_document = true ТІЛЬКИ якщо це офіційний документ України (Тризуб, 'Україна'/'Ukraine').
        2. set has_russian_markers = true ТІЛЬКИ якщо присутні будь-які згадки росії, рф, москви, герба рф чи російських органів."""
        
        response = await vision_model.generate_content_async(
            [image_part, prompt],
            generation_config={"response_mime_type": "application/json"}
        )
        # Очищення можливого маркдауну перед парсингом
        clean_json = re.sub(r'^```json\s*|\s*```$', '', response.text.strip(), flags=re.IGNORECASE)
        result = json.loads(clean_json)
        
        student = await db.get_student_by_tg_id(user_id)
        if not student:
            return {"success": False, "error": "Профіль не знайдено"}
        
        doc_id = student['id']

        # Якщо виявлено російські маркери
        if result.get("has_russian_markers"):
            await db.update_crm_stage(doc_id, "blocked")
            await db.clear_user_fsm(user_id)
            return {"success": False, "error": "Документ не пройшел перевірку безпеки."}

        # 6. Маршрутизація успішного українського документа
        if result.get("is_ua_document") and result.get("confidence", 0) > 0.6:
            student_data = student['data']
            
            await firestore_client.collection('Svitlo').document(doc_id).update({
                "ai_doc_valid": True,
                "ai_doc_type": result.get("doc_type", "unknown"),
                "crm_stage": "admin_review",
                "crm_stage_updated_at": db.get_kyivtime_now()
                })
            await db.set_user_fsm_state(user_id, "Registration:admin_review")
            
            # Server-Side Push: Сповіщаємо юзера про успіх
            try:
                await bot.send_message(
                    chat_id=user_id,
                    text=APPLICATION_RECEIVED_MSG
                )
            except Exception as e:
                logging.warning(f"Failed to notify user {user_id}: {e}")
            
            # Сповіщення в групу кураторів
            try:
                tg_username = student_data.get('telegramUsername', '').replace('@', '')
                keyboard = kb.get_admin_action_kb(doc_id, tg_username, include_details_btn=True)
                
                full_name = f"{student_data.get('first_name', '')} {student_data.get('last_name', '')}"
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
                        f"Очікує рішення куратора:"
                    ),
                    reply_markup=keyboard
                )
                return {"success": True}
            
            except Exception as e:
                logging.error(f"Failed to send admin notification: {e}")
        else:
            return {"success": False, "error": "Не знайдено українських маркерів. Переконайся, що документ добре видно у кадрі, та спробуй ще раз"}
            
    except Exception as e:
        logging.error(f"Vertex AI Vision Error: {e}")
        return {"success": False, "error": "Помилка обробки ШІ. Спробуй пізніше"}