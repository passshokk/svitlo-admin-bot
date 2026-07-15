import firebase_admin
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from cachetools import TTLCache

from datetime import datetime
from zoneinfo import ZoneInfo

# Initialize a TTL cache for storing frequently accessed data
student_cache = TTLCache(maxsize=1024, ttl=300)  # Cache up to 1024 items for 5 minutes

def get_kyivtime_now():
    kyiv_time = datetime.now(ZoneInfo("Europe/Kyiv"))
    return kyiv_time.strftime("%Y-%m-%d %H:%M:%S")

if not firebase_admin._apps:
    firebase_admin.initialize_app(options={'projectId': 'svitlo-auth-bot'})

db = firestore.AsyncClient()

# ==========================
# region --- Main Svitlo DB

async def get_student_by_tg_id(tg_id: int):
    if tg_id in student_cache:
        return student_cache[tg_id]
    
    doc_ref = db.collection('Svitlo').document(str(tg_id))
    doc = await doc_ref.get()
    
    student_data = None
    if doc.exists:
        student_data = {"id": doc.id, "data": doc.to_dict()}
    else:
        # Фолбек на пошук за полем
        query = db.collection('Svitlo').where(filter=FieldFilter('telegramId', '==', tg_id)).limit(1).stream()
        async for doc_item in query:
            student_data = {"id": doc_item.id, "data": doc_item.to_dict()}
            break
    
    student_cache[tg_id] = student_data # Записуємо в кеш
    return student_data

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
    student_cache.pop(tg_id, None) # Видаляємо ключ з об'єкта кешу

async def link_telegram_id(doc_id: str, tg_id: int):
    await db.collection('Svitlo').document(doc_id).update({'telegramId': tg_id})

async def grant_house_access(doc_id: str):
    """Ставить прапорець, що юзер вже отримав лінк на свій Хаус."""
    await db.collection('Svitlo').document(doc_id).update({"houseAccess": True})

# endregion

# ==========================
# region --- Registration Workflow

async def init_lead(tg_id: int, username: str):
    """Створює базовий документ ліда при /start, якщо його ще немає."""
    doc_ref = db.collection('Svitlo').document(str(tg_id))
    doc = await doc_ref.get()
    
    if not doc.exists:
        await doc_ref.set({
            "telegramId": tg_id,
            "username": username or "",
            "status": "lead",
            "crm_stage": "onboarding",
            "roles": [],
            "created_at": get_kyivtime_now()
        })

async def save_lead_profile(tg_id: int, personal_data: dict, next_crm_stage: str):
    """Зберігає зібрані дані та переводить ліда на наступний етап."""
    await db.collection('Svitlo').document(str(tg_id)).set({
        "personal_info": personal_data,
        "crm_stage": next_crm_stage,
        "crm_stage_updated_at": get_kyivtime_now()
    }, merge=True)

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
