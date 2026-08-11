# core/schooltoday.py
import os
import logging
import httpx

SCHOOL_TODAY_API_BASE_URL = "https://school-today.com"
SCHOOL_TODAY_API_KEY = os.getenv("SCHOOL_TODAY_API_KEY")
if not SCHOOL_TODAY_API_KEY:
    raise ValueError("SCHOOL_TODAY_API_KEY is missing in environment variables.")

_HEADERS = {
    "X-API-Key": SCHOOL_TODAY_API_KEY,
    "Content-Type": "application/json",
}

# Нативне строкове поле PupilModel, в яке пишемо наш Firestore doc_id як
# зовнішній унікальний ідентифікатор. PupilModel.id — це int32, присвоюваний
# SchoolToday при створенні, тому наш ID туди не влазить.
# TODO: підтвердити з розробником SchoolToday (personalFileNumber чи contractNumber)
EXTERNAL_ID_FIELD = "personalFileNumber"


async def get_custom_fields() -> list[dict]:
    """GET /v1/PupilCustomFields — список визначень кастомних полів учня."""
    url = f"{SCHOOL_TODAY_API_BASE_URL.rstrip('/')}/v1/PupilCustomFields"
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=_HEADERS)
        if response.status_code != 200:
            logging.error(f"SchoolToday get_custom_fields error: {response.text}")
        response.raise_for_status()
        data = response.json()
        return data.get("customFields", [])


async def get_pupils() -> list[dict]:
    """GET /v1/Pupils — усі учні школи."""
    url = f"{SCHOOL_TODAY_API_BASE_URL.rstrip('/')}/v1/Pupils"
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=_HEADERS, timeout=60)
        if response.status_code != 200:
            logging.error(f"SchoolToday get_pupils error: {response.text}")
        response.raise_for_status()
        return response.json().get("pupils", [])


async def get_pupil(pupil_id: int) -> dict:
    """GET /v1/Pupils/{id} — дані одного учня (API загортає їх у ключ `pupil`)."""
    url = f"{SCHOOL_TODAY_API_BASE_URL.rstrip('/')}/v1/Pupils/{pupil_id}"
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=_HEADERS)
        if response.status_code != 200:
            logging.error(f"SchoolToday get_pupil error: {response.text}")
        response.raise_for_status()
        return response.json().get("pupil", {})


async def create_or_update_pupil(payload: dict, pupil_id: int = 0) -> dict:
    """PUT /v1/Pupils/{id} — створення (id=0) або оновлення учня."""
    url = f"{SCHOOL_TODAY_API_BASE_URL.rstrip('/')}/v1/Pupils/{pupil_id}"
    async with httpx.AsyncClient() as client:
        response = await client.put(url, headers=_HEADERS, json=payload)
        if response.status_code not in (200, 201, 204):
            logging.error(f"SchoolToday create_or_update_pupil error: {response.text}")
        response.raise_for_status()
        return response.json() if response.content else {}


def map_svitlo_to_pupil_payload(doc_id: str, svitlo_doc: dict) -> dict:
    """
    Будує тіло запиту PupilModel з документа Svitlo (Firestore).

    Поля, яких немає нативно в PupilModel (телефон батьків, house, leadSource
    тощо), йдуть у customData як пари name/value — назви полів мають точно
    збігатися з тими, що розробник SchoolToday створить у себе в адмінці.
    """
    custom_data = [
        {"name": "Telegram ID", "value": str(svitlo_doc.get("telegramId", ""))},
        {"name": "Parent Full Name", "value": f"{svitlo_doc.get('parentFirstName', '')} {svitlo_doc.get('parentLastName', '')}".strip()},
        {"name": "Parent Email", "value": svitlo_doc.get("parentEmail", "")},
        {"name": "Parent Phone", "value": svitlo_doc.get("parentPhone", "")},
        {"name": "Lead Source", "value": svitlo_doc.get("leadSource", "")},
        {"name": "Has Health Issues", "value": "Так" if svitlo_doc.get("hasHealthIssues") else "Ні"},
        {"name": "Health Issues Details", "value": svitlo_doc.get("healthIssuesDetails", "")},
        {"name": "House", "value": svitlo_doc.get("house", "")},
        {"name": "Is Displaced", "value": "Так" if svitlo_doc.get("isDisplaced") else "Ні"},
    ]

    return {
        "firstName": svitlo_doc.get("firstName", ""),
        "lastName": svitlo_doc.get("lastName", ""),
        "birthday": svitlo_doc.get("birthDate"),
        EXTERNAL_ID_FIELD: doc_id,
        # TODO: підтвердити з розробником SchoolToday
        "gender": None,  # мапінг "Male"/"Female" -> int gender, значення enum невідомі
        "classID": None,  # немає ендпоінта для отримання валідних classID
        "pupilTypeID": None,  # значення enum невідомі
        "customData": custom_data,
    }
