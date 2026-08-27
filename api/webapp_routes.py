# api/webapp_routes.py
import os
import hmac
import hashlib
import json
import base64
import re
import time
from urllib.parse import parse_qsl
from pathlib import Path
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import vertexai
from vertexai.generative_models import GenerativeModel, Part
import logging
import httpx
from fastapi import File, Form, UploadFile, Request, APIRouter, HTTPException

from core import database as db
from core.database import db as firestore_client
from core.bot_init import bot
from core.constants import APPLICATION_RECEIVED_MSG
from api.task_routes import schedule_admin_review_digest

# Приховує конкретний спам-варнінг Vertex AI SDK про rest_asyncio fallback на grpc
class _SuppressVertexAsyncRestWarning(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return "REST async clients requires async credentials" not in record.getMessage()

logging.getLogger().addFilter(_SuppressVertexAsyncRestWarning())

webapp_router = APIRouter()
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Ініціалізація Vertex AI (бере credentials з сервіс-акаунта Cloud Run)
vertexai.init(project="svitlo-auth-bot", location="global")
vision_model = GenerativeModel("gemini-3.5-flash-lite")

# Ліміти захисту ендпоінта
MAX_INITDATA_AGE = 3600          # initData живе годину, далі — реджект (анти-replay)
MAX_IMAGE_BYTES = 6 * 1024 * 1024  # 6 МБ при 512Mi RAM контейнера
ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp"}

BLOCKED_TIMEZONES = {
    "Europe/Moscow", "Europe/Samara", "Asia/Yekaterinburg", 
    "Europe/Volgograd", "Asia/Omsk", "Asia/Novosibirsk", 
    "Asia/Krasnoyarsk", "Asia/Irkutsk", "Asia/Yakutsk", 
    "Asia/Vladivostok", "Asia/Magadan", "Asia/Kamchatka", "Asia/Anadyr"
}

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

        # hmac.compare_digest замість == — захист від timing-атак
        if not hmac.compare_digest(calculated_hash, received_hash):
            return False

        # Перевірка свіжості: без неї перехоплений initData валідний вічно (replay)
        auth_date = int(parsed_data.get("auth_date", 0))
        if auth_date <= 0 or (time.time() - auth_date) > MAX_INITDATA_AGE:
            logging.warning("initData rejected: stale auth_date")
            return False

        return True
    except Exception:
        return False

# Раніше запитували саме лише countryCode і одразу зводили відповідь до bool.
# Решта полів приходить тим самим запитом безкоштовно, а в причині блокування
# вони — головне: без ISP/AS і ознак proxy/hosting неможливо відрізнити
# людину з російського домашнього провайдера від когось за VPN-виходом.
GEOIP_FIELDS = "status,message,countryCode,country,regionName,city,isp,org,as,proxy,hosting,mobile,query"


async def geoip_lookup(ip: str) -> dict:
    """GeoIP-довідка по IP. Порожній dict, якщо перевірку не виконано.

    Свідомо НЕ кидає: GeoIP тут — допоміжний сигнал, і його недоступність
    не повинна валити скан документа. Ключ "unavailable" відрізняє
    «перевірили й це не РФ» від «перевірити не вдалося» — раніше обидва
    випадки давали однаковий False.
    """
    if ip in ("127.0.0.1", "localhost", "unknown"):
        return {"unavailable": f"локальна або невідома адреса ({ip})"}
    try:
        async with httpx.AsyncClient(timeout=1.5) as client:
            resp = await client.get(f"http://ip-api.com/json/{ip}?fields={GEOIP_FIELDS}")
            if resp.status_code != 200:
                return {"unavailable": f"ip-api.com HTTP {resp.status_code}"}
            data = resp.json()
            if data.get("status") != "success":
                return {"unavailable": f"ip-api.com: {data.get('message') or 'status != success'}"}
            return data
    except Exception as e:
        logging.warning(f"GeoIP check failed for {ip}: {e}")
        return {"unavailable": f"{type(e).__name__}: {e}"}


def format_geoip(geo: dict) -> str:
    """GeoIP-дані рядками для причини блокування."""
    if geo.get("unavailable"):
        return f"GeoIP: перевірку не виконано ({geo['unavailable']})"

    location = " / ".join(p for p in (geo.get("country"), geo.get("regionName"), geo.get("city")) if p)
    lines = [
        f"GeoIP: {geo.get('countryCode') or '??'} — {location or 'локацію не визначено'}",
        f"Провайдер: {geo.get('isp') or '—'} · {geo.get('as') or '—'}",
    ]
    if geo.get("org") and geo.get("org") != geo.get("isp"):
        lines.append(f"Організація: {geo['org']}")
    # Ці три прапорці — те, заради чого варто дивитись у причину руками:
    # proxy/hosting майже завжди означає VPN або дата-центр, а не домашню мережу.
    flags = [name for name, key in (("proxy/VPN", "proxy"), ("хостинг/дата-центр", "hosting"), ("мобільна мережа", "mobile")) if geo.get(key)]
    lines.append(f"Ознаки: {', '.join(flags) if flags else 'не виявлено'}")
    return "\n".join(lines)

@webapp_router.get("/webapp/camera", response_class=HTMLResponse)
async def get_scanner_ui():
    html_path = Path(__file__).parent / "scanner.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))

@webapp_router.post("/api/vision")
async def process_vision(
    request: Request,
    image: UploadFile = File(...),
    init_data: str = Form(...),
    timezone: str | None = Form(default=None)
):
    # 1. Валідація Telegram init_data
    if not validate_tg_init_data(init_data, BOT_TOKEN):
        raise HTTPException(status_code=403, detail="Invalid InitData")
    
    try:
        parsed_data = dict(parse_qsl(init_data))
        user_data = json.loads(parsed_data['user'])
        user_id = user_data['id']
    except Exception:
        raise HTTPException(status_code=400, detail="Cannot parse user payload")

    student = await db.get_student_by_tg_id(user_id)
    if not student:
        return {"success": False, "error": "Профіль не знайдено"}
    doc_id = student['id']

    # 2. Витягуємо IP-адресу клієнта з інфраструктури Cloud Run
    x_forwarded_for = request.headers.get("X-Forwarded-For")
    client_ip = x_forwarded_for.split(",")[0].strip() if x_forwarded_for else (request.client.host if request.client else "unknown")

    # Спільний «слід запиту» для причини блокування — однаковий для всіх трьох
    # перевірок нижче. Повний X-Forwarded-For, а не лише перший хоп: решта
    # ланцюга показує, чи йшов запит через проміжні проксі. User-Agent —
    # єдиний доступний тут відбиток клієнта.
    user_agent = request.headers.get("User-Agent") or "—"
    tg_username = user_data.get("username")
    request_trace = "\n".join([
        f"Telegram: id={user_id}" + (f" @{tg_username}" if tg_username else " (без юзернейму)"),
        f"IP: {client_ip}",
        f"X-Forwarded-For: {x_forwarded_for or '—'}",
        f"Таймзона пристрою: {timezone or 'не передано'}",
        f"User-Agent: {user_agent}",
    ])

    # 3. Перевірка 1: GeoIP
    geo = await geoip_lookup(client_ip)
    if geo.get("countryCode") == "RU":
        await db.update_crm_stage(doc_id, "blocked", reason="\n".join([
            "Правило: GeoIP-перевірка IP-адреси — країна RU",
            format_geoip(geo),
            request_trace,
        ]))
        await db.clear_user_fsm(user_id)
        return {"success": False, "error": "Доступ обмежено за регіональними параметрами мережі"}

    # 4. Перевірка 2: Таймзона пристрою
    if timezone in BLOCKED_TIMEZONES:
        # GeoIP тут уже пораховано вище — докладаємо його ЗАВЖДИ, навіть коли
        # він не збігається з таймзоною. Саме розбіжність і цікава: таймзона
        # Europe/Moscow при польському IP читається інакше, ніж коли обидва
        # сигнали вказують в один бік.
        await db.update_crm_stage(doc_id, "blocked", reason="\n".join([
            f"Правило: таймзона пристрою «{timezone}» у списку заблокованих",
            format_geoip(geo),
            request_trace,
        ]))
        await db.clear_user_fsm(user_id)
        return {"success": False, "error": "Регіональні параметри пристрою не підтримуються"}
    
    # 5. Валідація самого файлу до того, як він піде в Vertex AI
    image_bytes = await image.read()
    if not image_bytes:
        return {"success": False, "error": "Порожній файл. Перескануй документ"}
    if len(image_bytes) > MAX_IMAGE_BYTES:
        return {"success": False, "error": "Файл завеликий. Перескануй документ"}

    mime_type = (image.content_type or "image/jpeg").split(";")[0].strip().lower()
    if mime_type not in ALLOWED_MIME:
        return {"success": False, "error": "Непідтримуваний формат зображення"}

    # 6. Перевірка 3: ШІ-аналіз документа через Gemini Vision
    try:
        image_part = Part.from_data(data=image_bytes, mime_type=mime_type)

        prompt = """Аналізуй цей документ. Поверни суворий JSON:
        {
          "is_ua_document": true/false,
          "doc_type": "id_card/international_passport/birth_certificate/other",
          "has_russian_markers": true/false,
          "confidence": 0.0-1.0,
          "doc_first_name": "ім'я як надруковано в документі (латиницею, якщо є; інакше як є) або null, якщо не вдалось зчитати",
          "doc_last_name": "прізвище як надруковано в документі (латиницею, якщо є; інакше як є) або null, якщо не вдалось зчитати",
          "doc_dob": "дата народження у форматі ДД.ММ.РРРР як надруковано в документі, або null, якщо не вдалось зчитати"
        }
        Умови:
        1. is_ua_document = true ТІЛЬКИ якщо це офіційний документ України (Тризуб, 'Україна'/'Ukraine').
        2. set has_russian_markers = true ТІЛЬКИ якщо присутні будь-які згадки росії, рф, москви, герба рф чи російських органів.
        3. doc_first_name/doc_last_name/doc_dob — лише те, що фактично надруковано в документі. Нічого не вигадуй і не виправляй, якщо не впевнений — став null."""
        
        response = await vision_model.generate_content_async(
            [image_part, prompt],
            generation_config={"response_mime_type": "application/json"}
        )
        # Очищення можливого маркдауну перед парсингом
        clean_json = re.sub(r'^```json\s*|\s*```$', '', response.text.strip(), flags=re.IGNORECASE)
        result = json.loads(clean_json)

        # Якщо виявлено російські маркери
        if result.get("has_russian_markers"):
            # Кладемо ВСЮ відповідь моделі, а не самий doc_type. Це рішення
            # ухвалює ШІ, тож при апеляції треба бачити, на чому саме він його
            # ухвалив: низька confidence разом з is_ua_document=true — привід
            # передивитись руками, а не просто підтвердити блок. Зчитані з
            # документа ПІБ/ДН лишаємо тут же — за ними видно, чи модель
            # взагалі дивилась на той документ, який людина надіслала.
            confidence = result.get("confidence")
            doc_read = " · ".join(
                str(v) for v in (result.get("doc_first_name"), result.get("doc_last_name"), result.get("doc_dob")) if v
            )
            await db.update_crm_stage(doc_id, "blocked", reason="\n".join([
                "Правило: Gemini Vision виставив has_russian_markers=true для завантаженого документа",
                f"Тип документа за версією моделі: {result.get('doc_type') or 'не визначено'}",
                f"Український документ за версією моделі: {result.get('is_ua_document')}",
                f"Впевненість моделі: {round(float(confidence) * 100)}%" if isinstance(confidence, (int, float)) else "Впевненість моделі: не повернуто",
                f"Зчитано з документа: {doc_read or 'нічого не зчитано'}",
                f"Файл: {mime_type}, {len(image_bytes) // 1024} КБ",
                format_geoip(geo),
                request_trace,
            ]))
            await db.clear_user_fsm(user_id)
            return {"success": False, "error": "Документ не пройшов перевірку безпеки"}

        # Розділяємо гілки відмов, щоб підказка юзеру відповідала реальній причині
        if not result.get("is_ua_document"):
            return {
                "success": False,
                "error": "Це не схоже на український документ. Підготуй оргигінал і спробуй ще раз"
            }

        confidence = float(result.get("confidence", 0) or 0)
        if confidence <= 0.6:
            return {
                "success": False,
                "error": "Зображення нечітке. Протри камеру, додай світла й перескануй документ"
            }

        # --- Маршрутизація успішного українського документа ---
        student_data = student['data']

        ai_info = {
            "docType": result.get("doc_type", "unknown"),
            "firstName": result.get("doc_first_name"),
            "lastName": result.get("doc_last_name"),
            "birthDate": result.get("doc_dob"),
            "confidence": confidence,
        }

        await firestore_client.collection('Svitlo').document(doc_id).update({
            "aiInfo": ai_info,
        })
        await db.update_crm_stage(doc_id, "admin_review")
        await db.set_user_fsm_state(user_id, "Registration:admin_review")
        # Розгляд заявок — у Solar Panel, тож єдиний проактивний сигнал
        # куратору про нову заявку тепер це відкладений дайджест, а не
        # миттєве повідомлення з кнопками (те нижче — на видалення).
        await schedule_admin_review_digest()

        # Прибираємо технічні повідомлення сканера (interlude2 + інструкція), лишаючи чат чистим
        try:
            fsm_doc = await firestore_client.collection("FSM_Sessions").document(str(user_id)).get()
            scanner_msg_ids = (fsm_doc.to_dict() or {}).get("data", {}).get("scanner_msg_ids", []) if fsm_doc.exists else []
            for msg_id in scanner_msg_ids:
                try:
                    await bot.delete_message(chat_id=user_id, message_id=msg_id)
                except Exception:
                    pass
        except Exception as e:
            logging.warning(f"Failed to cleanup scanner messages for {user_id}: {e}")

        # Server-Side Push: Сповіщаємо юзера про успіх
        try:
            await bot.send_message(
                chat_id=user_id,
                text=APPLICATION_RECEIVED_MSG
            )
        except Exception as e:
            logging.warning(f"Failed to notify user {user_id}: {e}")

        # Розгляд заявки — повністю в Solar Panel (єдиний канал відколи
        # approve()/reject() там отримали повну паритетність з тим, що робив
        # цей блок: зарахування SchoolToday, інвайт у чат групи, детальна
        # причина блокування). Раніше тут стояло повідомлення в ADMIN_GROUP_ID
        # з кнопками lead_details_/lead_block_/lead_approve_ — усі три
        # відповідні хендлери в bot/reg_funnel.py і клавіатури в
        # bot/keyboards.py видалені разом із цим блоком.

        return {"success": True}

    except Exception as e:
        logging.exception(f"Vertex AI Vision Error: {e}")
        return {"success": False, "error": "Помилка обробки ШІ. Спробуй пізніше"}