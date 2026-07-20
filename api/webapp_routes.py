# api/webapp_routes.py
import os
import hmac
import hashlib
from urllib.parse import parse_qsl
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

webapp_router = APIRouter()
BOT_TOKEN = os.getenv("BOT_TOKEN")

class VisionPayload(BaseModel):
    image_base64: str
    init_data: str

def validate_tg_init_data(init_data: str, token: str) -> bool:
    """Криптографічна валідація даних від Telegram Mini App"""
    try:
        parsed_data = dict(parse_qsl(init_data))
        if "hash" not in parsed_data:
            return False
            
        received_hash = parsed_data.pop("hash")
        
        # Сортуємо ключі за алфавітом, як вимагає Telegram
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed_data.items()))
        
        secret_key = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
        calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        
        return calculated_hash == received_hash
    except Exception:
        return False

@webapp_router.get("/webapp/camera", response_class=HTMLResponse)
async def get_scanner_ui():
    """Віддає HTML фронтенд WebApp"""
    html_path = Path(__file__).parent / "scanner.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))

@webapp_router.post("/api/vision")
async def process_vision(payload: VisionPayload):
    """Приймає Base64 фотографію з фронтенду та передає її в OpenAI."""
    # 1. Захист від підробки запитів
    if not validate_tg_init_data(payload.init_data, BOT_TOKEN):
        raise HTTPException(status_code=403, detail="Invalid Telegram InitData")
    
    # Витягуємо user_id з init_data (опціонально, щоб знати, чий це документ)
    parsed_data = dict(parse_qsl(payload.init_data))
    # В реальності user_data це JSON рядок, можна спарсити для логів
    
    # TODO: Етап 2. Виклик OpenAI gpt-4o-mini
    # base64_data = payload.image_base64.split(",")[1]
    
    # Тимчасова заглушка для перевірки зв'язки Фронт <-> Бек
    return {"success": True, "message": "Зв'язка працює"}