from datetime import date, datetime
import html
import os
from zoneinfo import ZoneInfo
import httpx
import re
import phonenumbers
from aiogram.types import BotCommand, BotCommandScopeChat, Message
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)

from core import config as cfg
from core.constants import BENIGN_TELEGRAM_BADREQUESTS

# ====================================================================================
# region Messaging
# ====================================================================================

async def step_answer(target: Message, text: str, **kwargs) -> Message:
    """Відповідає без звуку/вібро. Для повторюваних кроків анкети (питання, виправлення
    вводу) — щоб каскад технічних повідомлень під час реєстрації не провокував мут бота"""
    kwargs.setdefault("disable_notification", True)
    return await target.answer(text, **kwargs)


async def safe_edit_text(message: Message, text: str, **kwargs) -> Message | None:
    """`message.edit_text` з ковтанням доброякісних збоїв Telegram.

    * `TelegramBadRequest` з BENIGN_TELEGRAM_BADREQUESTS (message is not
      modified / to edit not found / can't be edited / query is too old) —
      подвійний тап або повторна доставка callback-апдейту редагують
      повідомлення в той самий контент чи вже зникле повідомлення;
    * `TelegramNetworkError` / `TelegramRetryAfter` / `TelegramServerError` —
      тимчасовий мережевий збій, флуд-ліміт чи 5xx на холодному контейнері.

    Основна робота хендлера (запис у Firestore, зміна FSM) вже зроблена до
    цього виклику, тож зірване косметичне редагування не має валити апдейт.
    Реальні `TelegramBadRequest` (напр. поганий HTML) кидаються далі."""
    try:
        return await message.edit_text(text, **kwargs)
    except TelegramBadRequest as e:
        if any(s in str(e).lower() for s in BENIGN_TELEGRAM_BADREQUESTS):
            return None
        raise
    except (TelegramNetworkError, TelegramRetryAfter, TelegramServerError):
        return None


async def safe_delete(message: Message) -> bool:
    """`message.delete` з ковтанням очікуваних відмов Telegram. Повертає True,
    якщо повідомлення реально видалено.

    Бот може видаляти лише свої повідомлення віком < 48 год; повертається
    користувач, тисне стару інлайн-кнопку — і `delete()` кидає
    `TelegramBadRequest` (message can't be deleted for everyone / message to
    delete not found). Це не помилка логіки, а обмеження API."""
    try:
        await message.delete()
        return True
    except TelegramBadRequest as e:
        if any(s in str(e).lower() for s in BENIGN_TELEGRAM_BADREQUESTS):
            return False
        raise
    except (TelegramForbiddenError, TelegramNetworkError, TelegramRetryAfter, TelegramServerError):
        return False

# ====================================================================================
# region Format & Check
# ====================================================================================

def kyiv_today() -> date:
    """Сьогодні ЗА КИЄВОМ. date.today() на Cloud Run — це UTC-доба: з 00:00
    до 03:00 за Києвом вона ще вчорашня, і в день народження вік виходив на
    рік меншим (14-річного не переводило в старшу групу, реєстрація
    відмовляла 10-річному). Пояс продукту — Europe/Kyiv, як і в панелі
    (svitlo_admin_panel/core/tz.py)."""
    return datetime.now(ZoneInfo("Europe/Kyiv")).date()


def calculate_age(birth_date, on_date: date | None = None) -> int | None:
    """Повний вік у роках на дату `on_date` (дефолт — сьогодні).

    Приймає Firestore Timestamp / `datetime` / `date` / рядок ISO
    (`YYYY-MM-DD` або довший). Час і таймзону ігноруємо навмисно: ДН у базі
    лежить на 12:00 UTC, і будь-яке приведення до локального часу лише зсувало б
    день народження на добу. Повертає None, якщо дату не розпарсити — щоб
    викликач сам вирішив, що робити з такими записами, а не отримав 0 років.
    """
    if not birth_date:
        return None

    born: date | None = None
    if isinstance(birth_date, datetime):
        born = birth_date.date()
    elif isinstance(birth_date, date):
        born = birth_date
    elif isinstance(birth_date, str):
        try:
            born = date.fromisoformat(birth_date[:10])
        except ValueError:
            return None
    else:
        strftime = getattr(birth_date, "strftime", None)  # Firestore Timestamp тощо
        if not strftime:
            return None
        try:
            born = date.fromisoformat(strftime("%Y-%m-%d"))
        except ValueError:
            return None

    today = on_date or kyiv_today()
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


# Код семестру існує у ДВОХ формах, і читати треба обидві.
#
# Стара — `NN_YY-YY` («01_26-27»), нова — `YY-YY_NN` («26-27_01»). Рік
# переїхав уперед, щоб коди сортувались хронологічно звичайним порівнянням
# рядків: у старій формі «01_27-28» лягав між «01_26-27» і «02_26-27».
# Міграція даних (panel/scripts/migrate_semester_format.py) не миттєва й не
# дістає до SchoolToday, тож стару форму цей код мусить розуміти й далі.
_SEMESTER_OLD = re.compile(r"^(\d{1,2})_(\d{2}-\d{2})$")
_SEMESTER_NEW = re.compile(r"^(\d{2}-\d{2})_(\d{1,2})$")

# Діапазон без номера — `23-26`. Так позначені учні, що прийшли до того, як
# школа почала рахувати семестри: точного семестру для них немає, є вікно.
# Формат навмисно той самий `YY-YY`, що й у повного коду, тож сортується він
# на своєму місці — раніше за будь-який `25-26_NN`.
_SEMESTER_RANGE = re.compile(r"^(\d{2}-\d{2})$")

# Стара позначка тих самих учнів. У Firestore її вже немає (замінена на
# діапазон 20.09.2026), але в SchoolToday історичні значення лишаються, і
# нічого не коштує читати її й далі.
SEMESTER_LEGACY = "prior_semesters"


def format_semester(code) -> str:
    """Код семестру -> фраза для профілю.

    Раніше це був один рядок із `sem.split('_')`, який падав на всьому, що
    не має підкреслення, і на None — тобто профіль учня без семестру
    (а такі створюються, якщо календар недоступний) просто не рендерився.
    """
    if not isinstance(code, str) or not code.strip():
        return "at an unknown time"

    code = code.strip()
    if code == SEMESTER_LEGACY:
        return "many centuries ago..."

    match = _SEMESTER_RANGE.match(code)
    if match:
        # Вікно, а не семестр: точнішого ми просто не знаємо.
        return f"in 20{match.group(1)}"

    match = _SEMESTER_NEW.match(code)
    if match:
        year, number = match.groups()
    else:
        match = _SEMESTER_OLD.match(code)
        if not match:
            # Невідома форма: показуємо як є. Профіль із дивним семестром
            # кращий за профіль, якого немає.
            return code
        number, year = match.groups()

    # Номер віддаємо як у коді (без int()): «01» лишається «01», як було
    # до появи другої форми.
    return f"in {number} semester 20{year}"


def get_profile_text(data: dict) -> str:
    """Генерує HTML-профіль студента точно за новим дизайном та порядком полів"""
    full_name = f"{data.get('firstName', 'Невідомо')} {data.get('lastName', '')}".strip()
    email = data.get("email", "Немає")

    dob_raw = data.get("birthDate")
    if isinstance(dob_raw, str) and dob_raw:
        dob = dob_raw
    elif dob_raw:
        try:
            dob = dob_raw.astimezone(ZoneInfo("Europe/Kyiv")).strftime("%d %B %Y")
        except Exception:
            dob = str(dob_raw)
    else:
        dob = "Не вказано"

    group = "Older (14-18)" if data.get("ageGroup", "Не визначено") == "older" else "Younger (10-13)"
    house = data.get("house", "Ще не розподілено")

    joined = format_semester(data.get("semester"))

    user_roles = data.get("roles", [])

    roles_list = []
    for role_key in cfg.ROLE_MAP.keys():
        if role_key in user_roles:
            roles_list.append(cfg.ROLE_MAP[role_key])
            
    roles_text = "\n".join(roles_list) if roles_list else "Немає призначених ролей"

    return (
        f"<code>YOUR SVITLO PROFILE</code>\n\n"
        f"<b>Student:</b> {full_name}\n"
        f"<b>Email:</b> {email}\n"
        f"<b>Date of Birth:</b> {dob}\n\n"
        f"<b>Group:</b> {group}\n"
        f"<b>House:</b> {house}\n"
        f"<b>Joined SvitloSchool</b> {joined}\n"
        f"<b>Status:</b>\n"
        f"{roles_text}\n\n"
        f"<b>Account verified</b> in @svitlo_admin_bot"
    )

BLOCKED_COUNTRY_PATTERNS = {
    "росія", "росия", "россия", "росiя", "россiя", "рф", "раша", "мордор",
    "російськафедерація", "российскаяфедерация", "russianfederation",
    "russia", "rus", "ru", "rusia", "rossiya", "ruzzia", "rusnya", "русня"
}

def match_russian_country_input(text: str) -> dict | None:
    """Який САМЕ патерн спрацював, а не лише факт спрацювання.

    Повертає деталі збігу (або None), щоб причина блокування в CRM могла
    назвати конкретне правило й показати проміжні форми тексту. Без цього
    в картці лишалось голе «росія у полі країна», і чому воно спрацювало
    на неочевидному вводі (гомогліфи, підрядок) — не з'ясувати.
    """
    if not text:
        return None

    # 1. Приведення до нижнього регістру та видалення пробілів/спецсимволів
    clean_text = re.sub(r'[^a-zA-Zа-яА-ЯіІїЇєЄґҐ]', '', text.lower())

    # 2. Мапінг схожих латинських літер на кирилицю (захист від p-о-c-c-и-я)
    homoglyphs = str.maketrans({'p': 'р', 'o': 'о', 'c': 'с', 'a': 'а', 'e': 'е', 'x': 'х', 'y': 'у'})
    normalized_text = clean_text.translate(homoglyphs)

    # 3. Перевірка на прямий збіг або підрядок
    for pattern in BLOCKED_COUNTRY_PATTERNS:
        direct = pattern in clean_text
        if direct or pattern in normalized_text:
            return {
                "pattern": pattern,
                # Пряме входження чи лише після підміни гомогліфів — це різні
                # за силою сигнали: друге майже завжди означає навмисний обхід.
                "via": "пряме входження" if direct else "збіг лише після нормалізації гомогліфів",
                "clean": clean_text,
                "normalized": normalized_text,
                "exact": pattern == clean_text or pattern == normalized_text,
            }

    return None


def is_russian_country_input(text: str) -> bool:
    return match_russian_country_input(text) is not None


# Російські мобільні (+79) та міські (+73, +74, +78) діапазони; "89" — той самий
# мобільний діапазон у внутрішньому форматі набору (8 замість +7).
RU_PHONE_PREFIXES = ('+79', '+73', '+74', '+78', '89')


def match_russian_phone_prefix(phone: str) -> str | None:
    """Префікс, на якому спрацювало блокування (або None)."""
    clean_phone = re.sub(r'[^\d+]', '', phone)
    for prefix in RU_PHONE_PREFIXES:
        if clean_phone.startswith(prefix):
            return prefix
    return None


def is_russian_phone_number(phone: str) -> bool:
    return match_russian_phone_prefix(phone) is not None


# Українські мобільні коди без провідного нуля — для відновлення номерів,
# у яких загубився префікс країни (напр. "978815630" замість "+380978815630")
UA_MOBILE_CODES = {
    "39", "50", "63", "66", "67", "68", "73",
    "91", "92", "93", "94", "95", "96", "97", "98", "99",
}


def normalize_phone(raw: str) -> str | None:
    """Зводить номер до канонічного E.164 або повертає None, якщо він невалідний.

    Регулярка виду `^\\+[1-9]\\d{7,14}$` пропускає обрізані номери — саме через неї
    в базі осіли записи на кшталт `+38068823020` (11 цифр замість 12). Тут довжини й
    діапазони операторів перевіряє phonenumbers, тому такі номери відсіюються.

    Перед розбором застосовуємо два відновлення для українських шаблонів:
    дев'ять цифр із кодом оператора та десять цифр у форматі 0XXXXXXXXX.
    """
    if not raw or not raw.strip():
        return None

    # Якщо номерів кілька через кому — беремо перший
    digits = re.sub(r'\D', '', raw.split(',')[0])
    if not digits:
        return None

    if len(digits) == 9 and digits[:2] in UA_MOBILE_CODES:
        digits = "380" + digits
    elif len(digits) == 10 and digits[0] == "0" and digits[1:3] in UA_MOBILE_CODES:
        digits = "38" + digits

    try:
        parsed = phonenumbers.parse("+" + digits, None)
    except phonenumbers.NumberParseException:
        return None

    if not phonenumbers.is_valid_number(parsed):
        return None

    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)

def is_gibberish_name(name: str) -> bool:
    """Евристика для відсіювання явно фейкових імен: без жодної голосної або з довгим повтором однієї літери (напр. 'Xzcvbn', 'Aaaaaa')"""
    lower = name.lower()
    if not re.search(r'[aeiou]', lower):
        return True
    if re.search(r'(.)\1{2,}', lower):
        return True
    return False


def esc_html(value) -> str:
    """Екранує довільний текст користувача перед вставкою у HTML-повідомлення (parse_mode='HTML' за замовчуванням)"""
    if not value:
        return value
    return html.escape(str(value), quote=False)

def _levenshtein(a: str, b: str) -> int:
    """Класична відстань Левенштейна (кількість правок, щоб перетворити a на b)"""
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            curr[j] = min(
                prev[j] + 1,                 # видалення
                curr[j - 1] + 1,             # вставка
                prev[j - 1] + (ca != cb),    # заміна
            )
        prev = curr
    return prev[-1]

def suggest_email_domain_fix(email: str) -> str | None:
    """
    Якщо домен email схожий, але не ідентичний, на один з популярних (cfg.TRUSTED_EMAIL_DOMAINS),
    повертає виправлений варіант email (напр. gmail.con -> gmail.com). Інакше — None.
    Толерантність до похибки: 1 символ для коротких доменів (<=6), 2 символи для довших —
    щоб не плодити хибні збіги на коротких доменах на кшталт i.ua.
    """
    if "@" not in email:
        return None
    local_part, domain = email.rsplit("@", 1)
    if domain in cfg.TRUSTED_EMAIL_DOMAINS:
        return None

    best_domain, best_dist = None, None
    for trusted in cfg.TRUSTED_EMAIL_DOMAINS:
        if abs(len(domain) - len(trusted)) > 2:
            continue
        dist = _levenshtein(domain, trusted)
        threshold = 1 if len(trusted) <= 6 else 2
        if dist == 0 or dist > threshold:
            continue
        if best_dist is None or dist < best_dist:
            best_domain, best_dist = trusted, dist

    return f"{local_part}@{best_domain}" if best_domain else None

# endregion ==========================================================================
# region Notion
# ====================================================================================

# токен з налаштувань інтеграції Notion - https://app.notion.com/developers/connections
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
if not NOTION_TOKEN:
    raise ValueError("NOTION_TOKEN is missing in environment variables.")

# ID бази даних (рядок символів з URL між / і ?)
DATABASE_ID = "384f78e184b380b3858ee57ad13f2b54"

def format_notion_date(date_val) -> str:
    """Перетворює дату у правильний ISO формат з часовим поясом для Notion.
    Приймає як datetime (пряме читання з Firestore), так і рядок ISO — payload
    тікета проходить через Cloud Tasks (JSON), де datetime серіалізується в рядок."""
    if not date_val:
        return None

    if isinstance(date_val, str):
        date_val = datetime.fromisoformat(date_val)

    dt = date_val.astimezone(ZoneInfo("Europe/Kyiv"))
    return dt.isoformat()

async def export_to_notion(ticket_data: dict):
    """
    Відправляє закритий тікет у базу даних Notion.
    """
    url = "https://api.notion.com/v1/pages"
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }
    
    # Склеюємо масиви в текст, щоб Notion міг це відобразити в одному полі
    user_q_text = "\n---\n".join(ticket_data['user_raw_question'])
    curator_a_text = "\n---\n".join(ticket_data['curator_raw_answer'])
    
    # Структура даних для Notion (має збігатися з назвами полів у твоїй базі Notion)
    payload = {
        "parent": {"database_id": DATABASE_ID},
        "properties": {
            "ID Тікета": {"title": [{"text": {"content": str(ticket_data['ticket_id'])}}]},
            "Категорія": {"select": {"name": ticket_data['category']}},
            "Student ID": {"number": int(ticket_data['student_id'])},
            "Куратор": {"rich_text": [{"text": {"content": ticket_data['curator_name'] or "Невідомо"}}]},
            "Оцінка": {"number": ticket_data['rating'] or 0},
            "Created At": {"date": {"start": format_notion_date(ticket_data['created_at'])}},
            "Closed At": {"date": {"start": format_notion_date(ticket_data['closed_at'])}},
            "Статус": {"select": {"name": ticket_data['status']}}
        },
        "children": [
            {
                "object": "block", "type": "heading_2",
                "heading_2": {"rich_text": [{"text": {"content": "Питання студента"}}]}
            },
            {
                "object": "block", "type": "paragraph",
                "paragraph": {"rich_text": [{"text": {"content": user_q_text[:2000]}}]}
            },
            {
                "object": "block", "type": "heading_2",
                "heading_2": {"rich_text": [{"text": {"content": "Відповіді куратора"}}]}
            },
            {
                "object": "block", "type": "paragraph",
                "paragraph": {"rich_text": [{"text": {"content": curator_a_text[:2000]}}]}
            }
        ]
    }
    
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        try:
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code != 200:
                print(f"🛑 ТОЧНА ПОМИЛКА NOTION: {response.text}")
            response.raise_for_status()
            print(f"✅ Тікет {ticket_data['ticket_id']} успішно експортовано в Notion!")
        except Exception as e:
            print(f"❌ Помилка експорту в Notion: {e}")

# endregion ==========================================================================
# region Bot Commands Menu
# ====================================================================================

async def setup_owner_commands(bot) -> None:
    """Додає /testers у меню "/" лише в чаті власника (cfg.OWNER_ID), поверх його звичайних команд.
    Тестувальники її у меню не бачать (хоча сама команда все одно захищена фільтром на рівні хендлера)."""
    default_commands = await bot.get_my_commands()
    owner_commands = [
        BotCommand(command="testers", description="🧪 Тестувальники"),
        BotCommand(command="registration", description="🎓 Реєстрація: відкрита/закрита"),
    ] + default_commands
    await bot.set_my_commands(owner_commands, scope=BotCommandScopeChat(chat_id=cfg.OWNER_ID))

# endregion ==========================================================================
# region 
# ====================================================================================