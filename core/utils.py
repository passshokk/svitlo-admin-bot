from datetime import datetime
import html
import os
from zoneinfo import ZoneInfo
import httpx
import re
from aiogram.types import BotCommand, BotCommandScopeChat, Message

from core import config as cfg

# ====================================================================================
# region Messaging
# ====================================================================================

async def step_answer(target: Message, text: str, **kwargs) -> Message:
    """Відповідає без звуку/вібро. Для повторюваних кроків анкети (питання, виправлення
    вводу) — щоб каскад технічних повідомлень під час реєстрації не провокував мут бота"""
    kwargs.setdefault("disable_notification", True)
    return await target.answer(text, **kwargs)

# ====================================================================================
# region Format & Check
# ====================================================================================

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

    sem = data.get("semester")
    if sem == "prior_semesters":
        joined = "many centuries ago..."
    else:
        joined = f"in {sem.split('_')[0]} semester 20{sem.split('_')[1]}"
        
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

def is_russian_country_input(text: str) -> bool:
    if not text:
        return False
        
    # 1. Приведення до нижнього регістру та видалення пробілів/спецсимволів
    clean_text = re.sub(r'[^a-zA-Zа-яА-ЯіІїЇєЄґҐ]', '', text.lower())
    
    # 2. Мапінг схожих латинських літер на кирилицю (захист від p-о-c-c-и-я)
    homoglyphs = str.maketrans({'p': 'р', 'o': 'о', 'c': 'с', 'a': 'а', 'e': 'е', 'x': 'х', 'y': 'у'})
    normalized_text = clean_text.translate(homoglyphs)

    # 3. Перевірка на прямий збіг або підрядок
    for pattern in BLOCKED_COUNTRY_PATTERNS:
        if pattern in clean_text or pattern in normalized_text:
            return True
            
    return False

def is_russian_phone_number(phone: str) -> bool:
    clean_phone = re.sub(r'[^\d+]', '', phone)
    # Блокуємо всі російські мобільні (+79) та міські (+73, +74, +78) діапазони
    if clean_phone.startswith(('+79', '+73', '+74', '+78', '89')):
        return True
    return False

def is_gibberish_name(name: str) -> bool:
    """Евристика для відсіювання явно фейкових імен: без жодної голосної або з довгим повтором однієї літери (напр. 'Xzcvbn', 'Aaaaaa')"""
    lower = name.lower()
    if not re.search(r'[aeiou]', lower):
        return True
    if re.search(r'(.)\1{2,}', lower):
        return True
    return False

def format_ai_info_block(ai_info: dict) -> str:
    """Форматує весь блок ШІ-аналізу документа (тип, впевненість, зчитані ім'я/прізвище/ДН)
    для показу куратору. Без жодної автоматичної звірки з анкетою — рішення лишається за куратором."""
    ai_info = ai_info or {}

    doc_type = esc_html(ai_info.get("docType")) or "невідомо"
    confidence = ai_info.get("confidence")
    confidence_txt = f"{int(confidence * 100)}%" if isinstance(confidence, (int, float)) else "н/д"

    first_name = (ai_info.get("firstName") or "").title()
    last_name = (ai_info.get("lastName") or "").title()
    name_part = " ".join(p for p in [esc_html(first_name), esc_html(last_name)] if p) or "не вдалося зчитати"
    dob_part = esc_html(ai_info.get("birthDate")) or "не вдалося зчитати"

    return (
        f"<b>AI DOCUMENT REVIEW</b>\n"
        f"Тип: {doc_type} (точність: {confidence_txt})\n"
        f"Ім'я: {name_part}\nДН: {dob_part}"
    )

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
    """Перетворює дату у правильний ISO формат з часовим поясом для Notion"""
    if not date_val:
        return None

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
    
    async with httpx.AsyncClient() as client:
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
    ] + default_commands
    await bot.set_my_commands(owner_commands, scope=BotCommandScopeChat(chat_id=cfg.OWNER_ID))

# endregion ==========================================================================
# region 
# ====================================================================================