from datetime import datetime
import os
from zoneinfo import ZoneInfo
import httpx
import re
from aiogram.types import BotCommand, BotCommandScopeChat

from core import config as cfg

# ====================================================================================
# region Format & Check
# ====================================================================================

def get_profile_text(data: dict) -> str:
    """Генерує HTML-профіль студента точно за новим дизайном та порядком полів"""
    full_name = f"{data.get('name', 'Невідомо')} {data.get('surname', '')}".strip()
    email = data.get("email", "Немає")
    
    dob_raw = data.get("dateOfBirth")
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
        joined = f"in {sem.split('_')[0]} semester 20{sem.split('_')[2]}"
        
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
            
    dt = dt.replace(tzinfo=ZoneInfo("Europe/Kyiv"))
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
    """Додає /adddev, /removedev у меню "/" лише в чаті власника (cfg.OWNER_ID), поверх його звичайних команд.
    Інші розробники їх у меню не бачать (хоча самі команди все одно захищені фільтром на рівні хендлера)."""
    default_commands = await bot.get_my_commands()
    owner_commands = default_commands + [
        BotCommand(command="adddev", description="➕ Додати розробника"),
        BotCommand(command="removedev", description="➖ Прибрати розробника"),
    ]
    await bot.set_my_commands(owner_commands, scope=BotCommandScopeChat(chat_id=cfg.OWNER_ID))

