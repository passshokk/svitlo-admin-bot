# core/database.py
import firebase_admin
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo
from google.api_core.exceptions import AlreadyExists

def get_kyivtime_now():
    """Повертає київський час зараз у форматі `Timestamp` (datetime)."""
    return datetime.now(ZoneInfo("Europe/Kyiv"))

if not firebase_admin._apps:
    firebase_admin.initialize_app(options={'projectId': 'svitlo-auth-bot'})

db = firestore.AsyncClient()

# ==========================
# region --- Svitlo DB

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

async def find_duplicate_applicant(doc_id: str, email: str, phone: str) -> dict | None:
    """Шукає інші анкети (крім поточної) з тим самим email або телефоном — для антидубль-попередження куратору."""
    if email:
        query = db.collection('Svitlo').where(filter=FieldFilter('email', '==', email.lower().strip())).limit(3).stream()
        async for doc in query:
            if doc.id != doc_id:
                return {"id": doc.id, "data": doc.to_dict()}

    if phone:
        query = db.collection('Svitlo').where(filter=FieldFilter('phone', '==', phone.strip())).limit(3).stream()
        async for doc in query:
            if doc.id != doc_id:
                return {"id": doc.id, "data": doc.to_dict()}

    return None

async def grant_access_to_student(doc_id: str, tg_id: int):
    await db.collection('Svitlo').document(doc_id).update({
        'hasGroupAccess': True,
        'telegramId': tg_id
    })

async def link_telegram_id(doc_id: str, tg_id: int):
    await db.collection('Svitlo').document(doc_id).update({'telegramId': tg_id})

async def update_telegram_username(doc_id: str, username: str):
    """Синхронізує актуальний @username"""
    await db.collection('Svitlo').document(doc_id).update({'telegramUsername': username})

async def grant_house_access(doc_id: str):
    """Ставить прапорець, що юзер вже отримав лінк на свій Хаус"""
    await db.collection('Svitlo').document(doc_id).update({"hasHouseAccess": True})

# endregion

# ==========================
# region --- Registration Workflow

def generate_svitlo_id() -> str:
    """Генерує композитний ID (формат: SV-YYMMDD-XXXXXXXX)."""
    date_prefix = datetime.now(ZoneInfo("Europe/Kyiv")).strftime("%y%m%d")
    random_suffix = uuid.uuid4().hex[:8]
    return f"SV-{date_prefix}-{random_suffix}"

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
        
    now = get_kyivtime_now()
    
    payload = {
        # ⚙️ System & Tracking
        "semester": "01_26-27", #current semester number
        "telegramId": tg_id,
        "telegramUsername": username or "",
        "stage": "lead",
        "createdAt": now,
        "stageUpdatedAt": now,
        "followupStep": 0, # 0=none, 1=tg reminder 1, 2=tg reminder 2, 3=email reminder

        # 👤 Student Info
        "firstName": "",
        "lastName": "",
        "email": "",
        "phone": "",
        "gender": "",
        "birthDate": None,
        "ageGroup": "",

        # 📍 Location & IDP/Refugee Status
        "country": "",
        "city": "",
        "isDisplaced": False,
        "displacedRegion": "",

        # 👨‍👩‍👧 Parents / Guardians
        "parentFirstName": "",
        "parentLastName": "",
        "parentEmail": "",
        "parentPhone": "",

        # 🏥 Health & Marketing
        "leadSource": "",
        "hasHealthIssues": False,
        "healthIssuesDetails": "",

        # 📚 School Rules
        "rulesMistakes": 0,

        # 🤖 AI Verification
        "aiInfo": {},

        # 🔁 Anti-duplicate
        "possibleDuplicateId": "",

        # 🔐 Access & Roles
        "hasGroupAccess": False,
        "hasHouseAccess": False,
        "house": "Newbie",
        "roles": []
    }

    # Безкінечний цикл генерації ID для гарантії унікальності
    while True:
        custom_doc_id = generate_svitlo_id()
        doc_ref = db.collection('Svitlo').document(custom_doc_id)

        try:
            # .create() атомарно створить документ АБО викине помилку AlreadyExists
            await doc_ref.create(payload)
            await _log_stage_event(custom_doc_id, "lead", now)
            return custom_doc_id
        except AlreadyExists:
            # У разі колізії цикл одразу генерує новий ID та повторює спробу
            continue

async def save_lead_profile(doc_id: str, data: dict, next_stage: str):
    """
    Зберігає всі зібрані дані воронки у корінь документа Firebase (Flat Schema)
    та переводить ліда на наступний етап.
    """
    payload = {
        "firstName": data.get("firstName", ""),
        "lastName": data.get("lastName", ""),
        "email": data.get("email", ""),
        "phone": data.get("phone", ""),
        "gender": data.get("gender", ""),
        "birthDate": data.get("birthDate"),
        "ageGroup": data.get("ageGroup", ""),

        "country": data.get("country", ""),
        "city": data.get("city", ""),
        "isDisplaced": data.get("isDisplaced", False),
        "displacedRegion": data.get("displacedRegion", ""),

        "parentFirstName": data.get("parentFirstName", ""),
        "parentLastName": data.get("parentLastName", ""),
        "parentEmail": data.get("parentEmail", ""),
        "parentPhone": data.get("parentPhone", ""),

        "leadSource": data.get("leadSource", ""),
        "hasHealthIssues": data.get("hasHealthIssues", False),
        "healthIssuesDetails": data.get("healthIssuesDetails", ""),
    }
    await db.collection('Svitlo').document(doc_id).set(payload, merge=True)
    await update_crm_stage(doc_id, next_stage)

async def _log_stage_event(doc_id: str, stage: str, at):
    """
    Пише append-only подію переходу стадії в `StageEvents`.

    `Svitlo.stage`/`stageUpdatedAt` зберігають лише ПОТОЧНИЙ стан (перезаписуються),
    тому без окремого логу неможливо порахувати funnel-конверсію в часі
    (напр. "скільки лідів відвалилось на квізі правил у червні"). Ця колекція —
    єдине джерело історії для майбутньої аналітики/CRM.
    """
    await db.collection('StageEvents').document().set({
        "studentId": doc_id,
        "stage": stage,
        "at": at
    })

async def update_crm_stage(doc_id: str, next_stage: str):
    """
    Оновлює в `Svitlo` поточну стадію та timestamp останньої активності юзера,
    і логує сам перехід у `StageEvents`.
    """
    now = get_kyivtime_now()
    await db.collection('Svitlo').document(doc_id).update({
        "stageUpdatedAt": now,
        "stage": next_stage
    })
    await _log_stage_event(doc_id, next_stage, now)

async def increment_rules_mistake(doc_id: str):
    """Атомарно інкрементує лічильник неправильних відповідей у квізі правил."""
    await db.collection('Svitlo').document(doc_id).update({
        "rulesMistakes": firestore.Increment(1)
    })

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

# ==========================
# region --- Tester Access Control

_TESTERS_DOC = ("Config", "bot_settings")

async def _get_testers_map() -> dict[str, str | None]:
    """Повертає {str(tg_id): username} з поля testers у Config/bot_settings (порожній dict, якщо поля ще нема)."""
    doc = await db.collection(_TESTERS_DOC[0]).document(_TESTERS_DOC[1]).get()
    data = doc.to_dict() if doc.exists else {}
    return data.get("testers") or {}

async def get_tester_ids() -> set[int]:
    """Повертає telegram ID тестувальників з Firestore."""
    testers = await _get_testers_map()
    return {int(tg_id) for tg_id in testers}

async def get_testers() -> dict[int, str | None]:
    """Повертає {tg_id: username} для показу списку тестувальників (/testers)."""
    testers = await _get_testers_map()
    return {int(tg_id): username for tg_id, username in testers.items()}

async def add_tester_id(tg_id: int, username: str | None = None):
    """Додає пару (tg_id, username) до списку тестувальників.
    Важливо: тут потрібен саме вкладений dict, а не крапкова строка-ключ.
    set(merge=True) мерджить вкладені dict-и структурно, але НЕ парсить крапку в ключі
    (на відміну від update()) — інакше замість testers.{id} у мапі testers
    вийде буквальне плоске поле з ім'ям "testers.{id}"."""
    await db.collection(_TESTERS_DOC[0]).document(_TESTERS_DOC[1]).set(
        {"testers": {str(tg_id): username}},
        merge=True,
    )

async def remove_tester_id(tg_id: int):
    """Прибирає пару (tg_id, username) зі списку тестувальників."""
    await db.collection(_TESTERS_DOC[0]).document(_TESTERS_DOC[1]).update(
        {f"testers.{tg_id}": firestore.DELETE_FIELD}
    )

# endregion

# ==========================
# region --- Registration Period Control

async def get_registration_open() -> bool:
    """Чи відкрита реєстрація нових лідів (кнопка "Хочу зареєструватись" на /start).
    Керується овнером через /registration. За замовчуванням закрита."""
    doc = await db.collection(_TESTERS_DOC[0]).document(_TESTERS_DOC[1]).get()
    data = doc.to_dict() if doc.exists else {}
    return bool(data.get("registrationOpen", False))

async def set_registration_open(is_open: bool):
    await db.collection(_TESTERS_DOC[0]).document(_TESTERS_DOC[1]).set(
        {"registrationOpen": is_open},
        merge=True,
    )

# endregion
