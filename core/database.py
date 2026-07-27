# core/database.py
import firebase_admin
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from datetime import datetime
from zoneinfo import ZoneInfo

def get_kyivtime_now():
    kyiv_time = datetime.now(ZoneInfo("Europe/Kyiv"))
    return kyiv_time.strftime("%Y-%m-%d %H:%M:%S")

if not firebase_admin._apps:
    firebase_admin.initialize_app(options={'projectId': 'svitlo-auth-bot'})

db = firestore.AsyncClient()

# ==========================
# region --- Main Svitlo DB

async def get_student_by_tg_id(tg_id: int) -> dict | None:
    """Пошук документа в колекції Svitlo. Виключно прямий запит у БД."""
    query = db.collection('Svitlo').where(filter=FieldFilter('telegramId', '==', tg_id)).limit(1).stream()
    async for d in query:
        return {"id": d.id, "data": d.to_dict()}
    return None

async def get_student_by_email(email: str):
    """Бере дані студента за його електронною поштою."""
    query = db.collection('Svitlo').where(filter=FieldFilter('email', '==', email.lower().strip())).limit(1).stream()
    async for doc in query:
        return {"id": doc.id, "data": doc.to_dict()}
    return None

async def grant_access_to_student(doc_id: str, tg_id: int):
    await db.collection('Svitlo').document(doc_id).update({
        'groupAccess': True,
        'telegramId': tg_id
    })

async def link_telegram_id(doc_id: str, tg_id: int):
    await db.collection('Svitlo').document(doc_id).update({'telegramId': tg_id})

async def grant_house_access(doc_id: str):
    """Ставить прапорець, що юзер вже отримав лінк на свій Хаус."""
    await db.collection('Svitlo').document(doc_id).update({"houseAccess": True})

# endregion

# ==========================
# region --- Registration Workflow

async def init_lead(tg_id: int, username: str | None) -> str:
    """Створює новий документ ліда в Firebase.

    Ініціалізує всі колонки профілю студента (Flat Schema) із забезпеченням коректного відображення в Rowy.

    Parameters:
        tg_id: Telegram ID користувача.
        username: Юзернейм у Telegram (якщо є).

    Returns:
        str: Автогенерований ID створеного документа у Firestore.
    """
    existing = await get_student_by_tg_id(tg_id)
    if existing:
        return existing['id']
        
    doc_ref = db.collection('Svitlo').document() # Автогенерація ID
    now = get_kyivtime_now()
    
    payload = {
        # ⚙️ System & Tracking
        "semester": "1_26-27", #current semester number
        "telegramId": tg_id,
        "telegramUsername": username or "",
        "crm_stage": "lead",
        "created_at": now,
        "crm_stage_updated_at": now,
        "onboarding_followup_sent": 0,
        
        # 👤 Student Info
        "name": "",
        "surname": "",
        "email": "",
        "phone": "",
        "gender": "",
        "dateOfBirth": None, 
        "ageGroup": "",
        
        # 📍 Location & IDP/Refugee Status
        "country": "",
        "city": "",
        "displaced_status": False,
        "displaced_region": "",
        
        # 👨‍👩‍👧 Parents / Guardians
        "parent_first_name": "",
        "parent_last_name": "",
        "parent_email": "",
        "parent_phone": "",
        
        # 🏥 Health & Marketing
        "lead_source": "",
        "health_issues_bool": False,
        "health_issues_details": "",

        # 🤖 AI Verification
        "ai_doc_valid": False,
        "ai_doc_type": "",

        # 🔐 Access & Roles
        "groupAccess": False,
        "houseAccess": False,
        "house": "Newbie",
        "roles": []
    }
    await doc_ref.set(payload)
    
    return doc_ref.id

async def save_lead_profile(doc_id: str, data: dict, next_crm_stage: str):
    """
    Зберігає всі зібрані дані воронки у корінь документа Firebase (Flat Schema)
    та переводить ліда на наступний етап.
    """
    payload = {
        "name": data.get("first_name", ""),
        "surname": data.get("last_name", ""),
        "email": data.get("email", ""),
        "phone": data.get("phone", ""),
        "gender": data.get("gender", ""),
        "dateOfBirth": data.get("dateOfBirth"),
        "ageGroup": data.get("ageGroup", ""),
        
        "country": data.get("country", ""),
        "city": data.get("city", ""),
        "displaced_status": data.get("is_displaced", False),
        "displaced_region": data.get("displaced_region", ""),
        
        "parent_first_name": data.get("parent_first_name", ""),
        "parent_last_name": data.get("parent_last_name", ""),
        "parent_email": data.get("parent_email", ""),
        "parent_phone": data.get("parent_phone", ""),
        
        "lead_source": data.get("lead_source", ""),
        "health_issues_bool": data.get("health_bool", False),
        "health_issues_details": data.get("health_details", ""),
        
        "crm_stage": next_crm_stage,
        "crm_stage_updated_at": get_kyivtime_now()
    }
    await db.collection('Svitlo').document(doc_id).set(payload, merge=True)
    # Видаляємо пусті ключі, щоб не перезаписати випадково існуючі None/дефолти
    # clean_payload = {k: v for k, v in payload.items() if v != ""}
    # await db.collection('Svitlo').document(doc_id).set(clean_payload, merge=True)

async def update_crm_stage(doc_id: str, next_crm_stage: str):
    """
    Оновлює timestamp останньої активності ліда.
    Використовується для таймера Follow-up задач у Cloud Tasks.
    """
    await db.collection('Svitlo').document(doc_id).update({
        "crm_stage_updated_at": get_kyivtime_now(),
        "crm_stage": next_crm_stage
    })

# endregion

# ==========================
# region --- User Email State DB

async def set_custom_state(tg_id: int, state: str): # для повідомлення про оновлення бази перед новим семестром
    await db.collection('BotUsers').document(str(tg_id)).set({'custom_state': state}, merge=True)


# endregion

# ==========================
# region --- Ticket System

async def create_ticket(ticket_id: int, student_id: int, category: str, first_message: str):
    """Створення тікета в базі"""
    doc_ref = db.collection('HelpTickets').document(str(ticket_id))
    await doc_ref.set({
        'ticket_id': int(ticket_id),
        'student_id': student_id,
        'category': category,
        'user_raw_question': [first_message],
        'curator_name': None,
        'curator_raw_answer': [], # Порожній масив для майбутніх відповідей
        'status': 'open',
        'rating': None,
        'created_at': get_kyivtime_now(),
        'closed_at': None
    })

async def get_ticket(ticket_id: int | str) -> dict | None:
    """Отримує всі дані тікета за його ID"""
    doc_ref = db.collection('HelpTickets').document(str(ticket_id))
    doc = await doc_ref.get()
    if doc.exists:
        return doc.to_dict()
    return None

async def get_active_ticket(student_id: int) -> dict | None:
    """Шукає відкритий тікет студента (open або in_progress)"""
    query = db.collection('HelpTickets').where(filter=FieldFilter('student_id', '==', student_id)).where(filter=FieldFilter('status', 'in', ['open', 'in_progress'])).limit(1)
    docs = await query.get()
    for doc in docs:
        return doc.to_dict()
    return None

async def append_user_message(ticket_id: str, message: str):
    """Додавання нових повідомлень студента в масив"""
    doc_ref = db.collection('HelpTickets').document(str(ticket_id))
    await doc_ref.update({
        'user_raw_question': firestore.ArrayUnion([message])
    })

async def append_curator_message(ticket_id: str, message: str):
    """Додавання відповідей куратора в масив"""
    doc_ref = db.collection('HelpTickets').document(str(ticket_id))
    await doc_ref.update({
        'curator_raw_answer': firestore.ArrayUnion([message])
    })

async def assign_curator(ticket_id: str, curator_name: str):
    """Закріплення тікета за куратором"""
    doc_ref = db.collection('HelpTickets').document(str(ticket_id))
    await doc_ref.update({
        'status': 'in_progress',
        'curator_name': curator_name
    })

async def close_ticket(ticket_id: str):
    """Закриття тікета"""
    doc_ref = db.collection('HelpTickets').document(str(ticket_id))
    await doc_ref.update({
        'status': 'closed',
        'closed_at': get_kyivtime_now()
    })

async def set_ticket_rating(ticket_id: str, rating: int):
    """Збереження оцінки NPS"""
    doc_ref = db.collection('HelpTickets').document(str(ticket_id))
    await doc_ref.update({'rating': rating})
    # Повертаємо оновлений документ для відправки в Notion
    doc = await doc_ref.get()
    return doc.to_dict()

# endregion

# ==========================
# region --- FSM Helpers

async def clear_user_fsm(user_id: int | str):
    """Ізольоване видалення сесії FSM."""
    await db.collection("FSM_Sessions").document(str(user_id)).delete()

async def set_user_fsm_state(user_id: int | str, state_str: str):
    """Ізольоване встановлення стейту FSM."""
    await db.collection("FSM_Sessions").document(str(user_id)).set(
        {"state": state_str}, 
        merge=True
    )

# endregion