from datetime import datetime
import os
from zoneinfo import ZoneInfo
import httpx

from core import config as cfg

def get_profile_text(data: dict) -> str:
    """Генерує HTML-профіль студента точно за новим дизайном та порядком полів"""
    full_name = f"{data.get('name', 'Невідомо')} {data.get('surname', '')}".strip()
    email = data.get("email", "Немає")
    dob = data.get("dateOfBirth").astimezone(ZoneInfo("Europe/Kyiv")).strftime("%d %B %Y")
    group = "Older (14-18)" if data.get("ageGroup", "Не визначено") == "older" else "Younger (10-13)"
    house = data.get("house", "Ще не розподілено")

    sem = data.get("semester")
    if sem == "prior_semesters":
        joined = "many centuries ago..."
    else:
        joined = f"in {sem.split('_')[0]} semester 20{sem.split('_')[2]}"
        
    raw_roles = data.get("roles")
    user_roles = [r for r in raw_roles.split("|")]

    roles_list = []
    for role_key in cfg.ROLE_MAP.keys():
        if role_key in user_roles:
            roles_list.append(cfg.ROLE_MAP[role_key])
    roles_text = "\n".join(roles_list)

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

# ====================================================================================

# токен з налаштувань інтеграції Notion - https://app.notion.com/developers/connections
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
if not NOTION_TOKEN:
    raise ValueError("NOTION_TOKEN is missing in environment variables.")

# ID бази даних (рядок символів з URL між / і ?)
DATABASE_ID = "384f78e184b380b3858ee57ad13f2b54"

def format_notion_date(date_str: str) -> str:
    """Перетворює рядок з бази у правильний ISO формат з часовим поясом для Notion"""
    if not date_str:
        return None
    dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
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

