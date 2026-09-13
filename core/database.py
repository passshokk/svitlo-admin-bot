# core/database.py
import logging
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

async def init_registration(tg_id: int, username: str | None) -> tuple[str, bool]:
    """Створює новий документ заявника в Firebase, одразу на стадії `personal_data`.

    Раніше тут існувала проміжна стадія `lead`, яку заводили ще на кліку
    «Хочу зареєструватись» (до того, як людина взагалі почала анкету) —
    вона спотворювала конверсію: не кожен, хто натиснув кнопку, робив хоча б
    мінімальний наступний крок. Тепер документ і сам відлік конверсії
    з'являються лише на кліку «Почати реєстрацію» (bot/reg_funnel.py::start_entering_data).

    Ініціалізує всі колонки профілю студента (Flat Schema) із забезпеченням коректного відображення в Rowy.

    Parameters:
        tg_id: Telegram ID користувача.
        username: Юзернейм у Telegram (якщо є).

    Returns:
        tuple[str, bool]: (ID документа у Firestore, чи це новостворений документ — False, якщо юзер
        просто повторно тиснув «Почати реєстрацію», маючи вже існуючий документ). Прапорець
        потрібен викликачу, щоб не заплановувати нагадування (send_reminder) повторно.
    """
    existing = await get_student_by_tg_id(tg_id)
    if existing:
        return existing['id'], False
        
    now = get_kyivtime_now()
    
    payload = {
        # ⚙️ System & Tracking
        "semester": await get_current_semester(),
        "telegramId": tg_id,
        "telegramUsername": username or "",
        "stage": "personal_data",
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
            # Створення заявки: попередньої стадії не існує, тож fromStage
            # свідомо порожній — це не втрачене значення, а його відсутність.
            await _log_stage_event(custom_doc_id, "personal_data", now)
            return custom_doc_id, True
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

async def _log_stage_event(doc_id: str, stage: str, at, from_stage: str | None = None,
                           actor: str = "bot", reason: str = ""):
    """
    Пише append-only подію переходу стадії в `StageEvents`.

    `Svitlo.stage`/`stageUpdatedAt` зберігають лише ПОТОЧНИЙ стан (перезаписуються),
    тому без окремого логу неможливо порахувати funnel-конверсію в часі
    (напр. "скільки лідів відвалилось на квізі правил у червні"). Ця колекція —
    єдине джерело історії для майбутньої аналітики/CRM.

    `fromStage` / `actor` / `reason` додані пізніше. Без них аналітика мусила
    ВГАДУВАТИ напрямок переходу: подія несла лише "куди", тож відкат заявки
    (`reg_restart`), ручне переставляння стадії з панелі й органічний рух
    воронкою виглядали однаково. Саме через це в core/analytics живе евристика
    `_latest_transition_minutes` — вона відновлює пари подій здогадом. Із
    цими полями те саме рахується точно.

    На старих документах цих полів немає, і це нормально: усі читачі мусять
    працювати з подією, у якій є лише `studentId`/`stage`/`at`.

    `actor`: "bot" — рух самого заявника через воронку; email куратора —
    рішення з панелі (там своя дзеркальна копія цієї функції).
    """
    payload = {
        "studentId": doc_id,
        "stage": stage,
        "at": at,
        "actor": actor,
    }
    # Порожні поля не пишемо: у Firestore вони коштують стільки ж, скільки
    # заповнені, а в аналітиці "" і відсутнє поле однаково означають "невідомо".
    if from_stage:
        payload["fromStage"] = from_stage
    if reason:
        payload["reason"] = reason
    await db.collection('StageEvents').document().set(payload)

async def update_crm_stage(doc_id: str, next_stage: str, reason: str = "",
                           from_stage: str | None = None):
    """
    Оновлює в `Svitlo` поточну стадію та timestamp останньої активності юзера,
    і логує сам перехід у `StageEvents`.

    `reason` має сенс лише для `blocked`: раніше автоматичні блокування
    (рос. номер/країна/місто, GeoIP, таймзона, рос. маркери в документі)
    писали в базу сам лише stage="blocked", тож в адмінці неможливо було
    з'ясувати, за що саме людину заблокувало. Тепер причина лягає в поле
    `blockReason`, яке панель показує у картці профілю.
    """
    now = get_kyivtime_now()
    payload = {
        "stageUpdatedAt": now,
        "stage": next_stage
    }
    if next_stage == "blocked" and reason:
        payload["blockReason"] = reason
        payload["blockedBy"] = "Бот (автоматична перевірка)"
        payload["blockedAt"] = now

    # Одне читання заради `fromStage` у лозі. Так, це +1 читання на кожен
    # перехід — але переходів кількасот на день, а без напрямку подія не
    # відрізняє рух уперед від відкату, і вся аналітика швидкості змушена
    # це вгадувати. `from_stage` можна передати згори, якщо стадія вже
    # відома виклику, — тоді читання не буде.
    if from_stage is None:
        snapshot = await db.collection('Svitlo').document(doc_id).get()
        from_stage = (snapshot.to_dict() or {}).get("stage") if snapshot.exists else None

    await db.collection('Svitlo').document(doc_id).update(payload)
    await _log_stage_event(doc_id, next_stage, now, from_stage=from_stage, reason=reason)

async def delete_student(doc_id: str):
    """Видаляє документ заявника з `Svitlo` повністю.

    Використовується при скасуванні реєстрації (`reg_restart`): за новим
    визначенням воронки документ узагалі не мав би існувати, якщо людина не
    дійшла бодай до `personal_data`, тож "скасувати" тепер означає прибрати
    запис, а не відкочувати stage назад (раніше відкочували на вже прибрану
    стадію `lead`). `StageEvents` НЕ чіпаємо — це append-only лог, і аналітика
    (core/pipeline.build_funnel) вже вміє рахувати "є подія, немає документа"
    окремим лічильником (`missing`), а не мовчки губити його.
    """
    await db.collection('Svitlo').document(doc_id).delete()

async def increment_rules_mistake(doc_id: str):
    """Атомарно інкрементує лічильник неправильних відповідей у квізі правил."""
    await db.collection('Svitlo').document(doc_id).update({
        "rulesMistakes": firestore.Increment(1)
    })

# endregion

# ==========================
# region --- Ticket System

# Колекція звернень у Svitlo Support Centre (до вересня 2026 називалась "HelpTickets",
# перейменована разом із ребрендингом Help Centre → Support Centre; дані перенесено).
TICKETS_COLLECTION = 'SupportCentreTickets'

async def create_ticket(ticket_id: int, student_id: int, category: str, first_message: str, thread_id: int | None = None):
    """Створення тікета в базі"""
    doc_ref = db.collection(TICKETS_COLLECTION).document(str(ticket_id))
    await doc_ref.set({
        'ticket_id': int(ticket_id),
        'student_id': student_id,
        'category': category,
        'thread_id': thread_id, # окрема гілка (forum topic) в CURATOR_GROUP_ID для цього тікета
        'user_raw_question': [first_message],
        'curator_name': None,
        'curator_raw_answer': [], # Порожній масив для майбутніх відповідей
        'status': 'open',
        'rating': None,
        'created_at': get_kyivtime_now(),
        # Заповнюються пізніше: assigned_at — коли куратор узяв тікет,
        # first_response_at — коли він уперше відповів. Разом вони дають
        # розклад очікування на "лежав нічийним" і "вели, але мовчали".
        'assigned_at': None,
        'first_response_at': None,
        'curator_history': [],
        'closed_at': None
    })

async def get_ticket(ticket_id: int | str) -> dict | None:
    """Отримує всі дані тікета за його ID"""
    doc_ref = db.collection(TICKETS_COLLECTION).document(str(ticket_id))
    doc = await doc_ref.get()
    if doc.exists:
        return doc.to_dict()
    return None

async def get_ticket_by_thread(thread_id: int) -> dict | None:
    """Шукає тікет за id його гілки (forum topic) в CURATOR_GROUP_ID.
    Кожен тікет живе у власній гілці, тож thread_id однозначно визначає тікет."""
    query = db.collection(TICKETS_COLLECTION).where(filter=FieldFilter('thread_id', '==', thread_id)).limit(1)
    docs = await query.get()
    for doc in docs:
        return doc.to_dict()
    return None

async def get_active_ticket(student_id: int) -> dict | None:
    """Шукає відкритий тікет студента (open або in_progress)"""
    query = db.collection(TICKETS_COLLECTION).where(filter=FieldFilter('student_id', '==', student_id)).where(filter=FieldFilter('status', 'in', ['open', 'in_progress'])).limit(1)
    docs = await query.get()
    for doc in docs:
        return doc.to_dict()
    return None

async def append_user_message(ticket_id: str, message: str):
    """Додавання нових повідомлень студента в масив"""
    doc_ref = db.collection(TICKETS_COLLECTION).document(str(ticket_id))
    await doc_ref.update({
        'user_raw_question': firestore.ArrayUnion([message])
    })

async def append_curator_message(ticket_id: str, message: str):
    """Додавання відповідей куратора в масив.

    Перша відповідь додатково ставить `first_response_at` — час до першої
    відповіді це головна метрика будь-якої підтримки, і дотепер її не було
    з чого порахувати взагалі. Ставимо лише якщо поля ще немає: ArrayUnion
    нижче спрацює на кожну репліку, а "перша" за визначенням одна.
    """
    doc_ref = db.collection(TICKETS_COLLECTION).document(str(ticket_id))
    payload = {'curator_raw_answer': firestore.ArrayUnion([message])}

    snapshot = await doc_ref.get()
    if snapshot.exists and not (snapshot.to_dict() or {}).get('first_response_at'):
        payload['first_response_at'] = get_kyivtime_now()

    await doc_ref.update(payload)

async def assign_curator(ticket_id: str, curator_name: str):
    """Закріплення тікета за куратором.

    `assigned_at` і `curator_history` додані заради аналітики підтримки:

    * без `assigned_at` неможливо порахувати, скільки тікет ПРОЛЕЖАВ нічийним
      — а це саме те, на що сварить крон /tasks/sla_check, тобто SLA існував
      як правило, але не як вимірюване число;
    * `curator_name` перезаписується при кожному перепризначенні, тож
      атрибуція була "останній виграв". `curator_history` — append-only
      поруч, сам `curator_name` лишається як є, щоб нічого не зламати.
    """
    doc_ref = db.collection(TICKETS_COLLECTION).document(str(ticket_id))
    await doc_ref.update({
        'status': 'in_progress',
        'curator_name': curator_name,
        'assigned_at': get_kyivtime_now(),
        'curator_history': firestore.ArrayUnion([curator_name]),
    })

async def close_ticket(ticket_id: str):
    """Закриття тікета (вирішено куратором)"""
    doc_ref = db.collection(TICKETS_COLLECTION).document(str(ticket_id))
    await doc_ref.update({
        'status': 'closed',
        'closed_at': get_kyivtime_now()
    })

async def cancel_ticket(ticket_id: str):
    """Скасування тікета самим студентом (окремо від 'closed', щоб не плутати
    з вирішеними куратором запитами в аналітиці/NPS)"""
    doc_ref = db.collection(TICKETS_COLLECTION).document(str(ticket_id))
    await doc_ref.update({
        'status': 'cancelled',
        'closed_at': get_kyivtime_now()
    })

async def set_ticket_rating(ticket_id: str, rating: int):
    """Збереження оцінки NPS"""
    doc_ref = db.collection(TICKETS_COLLECTION).document(str(ticket_id))
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

# Поточний семестр. Формат `номер_рік-рік` — саме його очікує core.utils при
# рендері профілю, а `prior_semesters` зарезервовано для перенесених учнів.
# Значення живе у Firestore, а не в коді: інакше з першим днем нового семестру
# всі реєстрації тихо отримували б чужу когорту, і помітили б це нескоро —
# нічого ж не падає.
_SEMESTER_FALLBACK = "01_26-27"


async def get_current_semester() -> str:
    """Код семестру, який проставляється новому ліду при створенні.

    Джерело №1 — навчальний календар (Config/academic_calendar). Саме він
    знає, що семестр починається з першого дня канікул перед ним, а не з
    першого уроку, тож нові ліди автоматично лягають у правильну когорту
    в ту саму мить, коли набір відкривається.

    Це прибирає рівно ту пастку, про яку попереджає коментар вище: раніше
    код треба було бумкнути вручну, і якщо забути — усі реєстрації тихо
    отримували чужу когорту, бо нічого не падало.

    Джерело №2 (фолбек) — старе ручне поле `currentSemester`. Воно лишається
    робочим, поки календар не залитий, і як аварійний важіль, якщо документ
    видалять. Розбіжність між ними логуємо: мовчки проігнорований ручний
    запис — це саме той різновид сюрпризу, якого тут і уникаємо.
    """
    doc = await db.collection(_TESTERS_DOC[0]).document(_TESTERS_DOC[1]).get()
    data = doc.to_dict() if doc.exists else {}
    manual = (data.get("currentSemester") or "").strip()

    try:
        from core.academic_calendar import load_calendar, today
        calendar = await load_calendar()
        derived = calendar.current_semester(today()) if calendar else None
    except Exception:
        # Календар — не критичний шлях: реєстрація не має падати через нього.
        logging.exception("Не вдалося взяти семестр із календаря")
        derived = None

    if derived:
        if manual and manual != derived:
            logging.warning(
                "Семестр: календар каже %s, ручне поле currentSemester — %s. "
                "Беремо календар; якщо потрібне саме ручне значення, правити треба календар.",
                derived, manual,
            )
        return derived

    return manual or _SEMESTER_FALLBACK


async def set_current_semester(value: str) -> None:
    await db.collection(_TESTERS_DOC[0]).document(_TESTERS_DOC[1]).set(
        {"currentSemester": value.strip()}, merge=True
    )


# Дата початку занять — показується учневі у вітальному повідомленні після
# схвалення заявки. Раніше була рядком у коді й устигла застаріти: зміна дати
# не має вимагати деплою.
_TERM_START_FALLBACK = "Понеділок, 14 вересня 2026 року"


async def get_term_start_date() -> str:
    doc = await db.collection(_TESTERS_DOC[0]).document(_TESTERS_DOC[1]).get()
    data = doc.to_dict() if doc.exists else {}
    return (data.get("termStartDate") or "").strip() or _TERM_START_FALLBACK


async def set_term_start_date(value: str) -> None:
    await db.collection(_TESTERS_DOC[0]).document(_TESTERS_DOC[1]).set(
        {"termStartDate": value.strip()}, merge=True
    )


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

async def get_next_registration_date() -> str | None:
    """Людиночитабельна дата наступного набору (напр. "28 жовтня").
    Показується лідам на кнопці-блокері, коли реєстрація закрита.

    Ручне значення (`/registration <дата>` від овнера) має ПРІОРИТЕТ —
    на відміну від семестру й дат початку навчання. Причина: відкриття
    набору це рішення школи, а не наслідок календаря. Календар лише
    підказує дату, коли овнер її не проставив, щоб замість порожнечі
    лід бачив хоч якийсь орієнтир.

    Літні канікули календар навмисно не пропонує як "наступний набір"
    (див. next_intake_start): після останнього семестру року дату
    призначає людина.
    """
    doc = await db.collection(_TESTERS_DOC[0]).document(_TESTERS_DOC[1]).get()
    data = doc.to_dict() if doc.exists else {}
    manual = (data.get("nextRegistrationDate") or "").strip()
    if manual:
        return manual

    try:
        from core.academic_calendar import format_date, load_calendar, today
        calendar = await load_calendar()
        intake = calendar.next_intake_start(today()) if calendar else None
        if intake:
            return format_date(intake, with_weekday=False)
    except Exception:
        logging.exception("Не вдалося взяти дату набору з календаря")
    return None

async def set_next_registration_date(date_str: str):
    await db.collection(_TESTERS_DOC[0]).document(_TESTERS_DOC[1]).set(
        {"nextRegistrationDate": date_str.strip()},
        merge=True,
    )

# endregion
