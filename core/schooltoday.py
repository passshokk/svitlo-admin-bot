# core/schooltoday.py
"""Клієнт SchoolToday Open API v1.

Ключові домовленості, на яких тримається цей модуль:

* `externalID` — ключ ідемпотентності. Учень отримує свій Firestore doc_id
  (`SV-YYMMDD-XXXXXXXX`), батько — `P-` плюс цифри E.164 без плюса. Плюс у ключ
  не пишемо: у query-рядку він декодується як пробіл.
* Створення — `PUT /{0}`, повертає `201` з тілом `{"id": …}`. Оновлення — `PATCH`
  з merge-семантикою. `PUT` на існуючий запис не використовуємо: він замінює
  картку цілком і затирає поля, яких немає в payload.
* Масиви (`customData`, `parentIDs`, `pupilIDs`) замінюються цілком навіть у
  `PATCH`. Тому `customData` перед записом зливаємо з тим, що вже на картці, а
  `pupilIDs` не передаємо ніколи — зв'язок ставимо лише з боку учня.
* Назви кастомних полів у школі змінюються (за тиждень їх перейменували чотири
  рази), тому звіряємось по `id` поля, а актуальну назву читаємо з довідника.
"""
import asyncio
import logging
import os
import re
from datetime import date, datetime
from typing import Any, Iterable

import httpx

from core.utils import normalize_phone

log = logging.getLogger(__name__)

BASE_URL = "https://school-today.com"
API_KEY = os.getenv("SCHOOL_TODAY_API_KEY")
if not API_KEY:
    raise ValueError("SCHOOL_TODAY_API_KEY is missing in environment variables.")

_HEADERS = {"X-API-Key": API_KEY, "Content-Type": "application/json"}
_TIMEOUT = httpx.Timeout(30.0, connect=10.0, read=120.0)

# Ретраї навмисно не робимо: виклики йдуть через Cloud Tasks, які повторюють самі.
# Ідемпотентність забезпечує externalID.

# Один клієнт на процес, а не новий на кожен виклик. Одне зарахування — чотири
# запити; без пулу кожен починався б із повного TLS-рукостискання, і на потоці
# реєстрацій це тисячі зайвих з'єднань.
_client: httpx.AsyncClient | None = None
_client_lock = asyncio.Lock()


async def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        async with _client_lock:
            if _client is None or _client.is_closed:
                _client = httpx.AsyncClient(
                    base_url=BASE_URL,
                    headers=_HEADERS,
                    timeout=_TIMEOUT,
                    limits=httpx.Limits(max_connections=20,
                                        max_keepalive_connections=10),
                )
    return _client


async def close_client() -> None:
    """Викликати на shutdown застосунку."""
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None

# ---------------------------------------------------------------------------
# Кастомні поля: звіряємось по id, назву беремо з довідника
# ---------------------------------------------------------------------------

FIELD_IDS = {
    "age_group": 22,
    "house": 23,            # legacy-копія нативного pupilTypeID, ми в неї НЕ пишемо
    "health": 27,
    "lead_source": 29,
    "tg_nickname": 30,
    "tg_id": 36,
    "roles": 37,            # мультивибір: значення через ';'
    "semester": 38,
    "health_details": 39,
    "idp": 40,
    "idp_region": 41,
}

# Поля, які пише бот.
#
# «house» і «age_group» свідомо поза списком — це кастомні копії фактів, що вже
# є в нативних полях: House дублює pupilTypeID (і розходився з ним у 139 картках),
# а вікова група виводиться з classID та birthDate. Обидва поля підлягають
# видаленню в налаштуваннях школи; доти ми в них просто не пишемо.
#
# «roles» веде школа — ми його лише читаємо й переносимо при повній заміні масиву.
WRITABLE_FIELDS = (
    "health", "health_details", "lead_source",
    "tg_nickname", "tg_id", "semester", "idp", "idp_region",
)

GENDER = {"Male": 0, "Female": 1}
AGE_GROUP = {"older": "14-18 років", "younger": "10-13 років"}
CLASS_BY_AGE_GROUP = {"older": "Older Student", "younger": "Younger Student"}
ROLE_SEPARATOR = ";"


class STError(Exception):
    """Помилка від SchoolToday з розібраним тілом.

    API повертає два різні формати: власний `{"errors": [...]}` і стандартний
    ValidationProblemDetails від фреймворку, коли payload не проходить біндинг.
    Гілкуватись у викликачі треба по `status` і `keys`, а не по тексту —
    повідомлення локалізовані (за замовчуванням українською).
    """

    def __init__(self, status: int, codes: list[str], keys: list[str], raw: Any):
        self.status = status
        self.codes = codes
        self.keys = keys
        self.raw = raw
        super().__init__(f"SchoolToday {status}: {', '.join(codes) or raw}")

    def touches(self, key: str) -> bool:
        return key.lower() in {k.lower() for k in self.keys}


def _parse_error(response: httpx.Response) -> STError:
    codes: list[str] = []
    keys: list[str] = []
    try:
        body = response.json()
    except ValueError:
        return STError(response.status_code, [], [], response.text)

    if isinstance(body, dict) and isinstance(body.get("errors"), list):
        for err in body["errors"]:
            if err.get("message"):
                codes.append(err["message"])
            for member in err.get("members") or []:
                if member.get("key"):
                    keys.append(member["key"])
    elif isinstance(body, dict) and isinstance(body.get("errors"), dict):
        # ValidationProblemDetails: {"errors": {"birthday": ["The value ..."]}}
        codes.append(body.get("title", "ValidationProblem"))
        keys.extend(body["errors"].keys())
    elif isinstance(body, dict) and body.get("title"):
        # Звичайний ProblemDetails — так приходять 401 і 403
        codes.append(body["title"])

    return STError(response.status_code, codes, keys, body)


async def _request(method: str, path: str, *, params: dict | None = None,
                   json: dict | None = None) -> httpx.Response:
    client = await get_client()
    response = await client.request(method, path, params=params, json=json)
    if response.status_code >= 400:
        error = _parse_error(response)
        log.error("SchoolToday %s %s -> %s", method, path, error)
        raise error
    return response


# ---------------------------------------------------------------------------
# Довідники. Читаються раз на процес: вони змінюються рідко, але змінюються.
# ---------------------------------------------------------------------------

_registry: dict[str, Any] | None = None
_registry_lock = asyncio.Lock()


async def get_registry() -> dict[str, Any]:
    """Кастомні поля, класи й типи учня одним словником.

    Падає гучно, якщо очікуваного поля немає: краще зупинити запис, ніж тихо
    писати в неіснуючу назву.
    """
    global _registry
    if _registry is not None:
        return _registry

    async with _registry_lock:
        if _registry is not None:
            return _registry

        fields = (await _request("GET", "/v1/PupilCustomFields")).json()["customFields"]
        by_id = {f["id"]: f for f in fields}

        missing = [alias for alias, fid in FIELD_IDS.items() if fid not in by_id]
        if missing:
            raise RuntimeError(
                "У школі немає кастомних полів: "
                + ", ".join(f"{a} (id={FIELD_IDS[a]})" for a in missing)
            )

        classes = (await _request("GET", "/v1/Classes")).json()
        types = (await _request("GET", "/v1/PupilTypes")).json()

        _registry = {
            "field_name": {a: by_id[i]["name"] for a, i in FIELD_IDS.items()},
            "field_options": {a: by_id[i].get("options") or [] for a, i in FIELD_IDS.items()},
            # У довіднику трапляються значення з пробілами по краях ("Caledonia "),
            # тому ключі нормалізуємо, а id беремо як є.
            "class_id": {c["name"].strip(): c["id"] for c in classes},
            "pupil_type_id": {t["name"].strip(): t["id"] for t in types},
        }
        return _registry


def reset_registry() -> None:
    """Скидає кеш довідників — для тестів і після змін у налаштуваннях школи."""
    global _registry
    _registry = None


# ---------------------------------------------------------------------------
# Читання
# ---------------------------------------------------------------------------

async def find_pupil(external_id: str) -> dict | None:
    pupils = (await _request(
        "GET", "/v1/Pupils", params={"externalID": external_id}
    )).json()["pupils"]
    return pupils[0] if pupils else None


async def find_parent(external_id: str) -> dict | None:
    parents = (await _request(
        "GET", "/v1/Parents", params={"externalID": external_id}
    )).json()["parents"]
    return parents[0] if parents else None


async def get_pupil(pupil_id: int) -> dict:
    return (await _request("GET", f"/v1/Pupils/{pupil_id}")).json()["pupil"]


async def get_parent(parent_id: int) -> dict:
    return (await _request("GET", f"/v1/Parents/{parent_id}")).json()["parent"]


async def list_pupils(*, is_hidden: bool | None = None,
                      class_id: int | None = None) -> list[dict]:
    params: dict[str, Any] = {}
    if is_hidden is not None:
        params["isHidden"] = str(is_hidden).lower()
    if class_id is not None:
        params["classID"] = class_id
    return (await _request("GET", "/v1/Pupils", params=params or None)).json()["pupils"]


async def list_parents(*, is_hidden: bool | None = None) -> list[dict]:
    params = {"isHidden": str(is_hidden).lower()} if is_hidden is not None else None
    return (await _request("GET", "/v1/Parents", params=params)).json()["parents"]


# ---------------------------------------------------------------------------
# Запис
# ---------------------------------------------------------------------------

async def create_pupil(payload: dict) -> int:
    response = await _request("PUT", "/v1/Pupils/0", json=payload)
    return response.json()["id"]


async def update_pupil(pupil_id: int, patch: dict) -> None:
    await _request("PATCH", f"/v1/Pupils/{pupil_id}", json=patch)


async def create_parent(payload: dict) -> int:
    response = await _request("PUT", "/v1/Parents/0", json=payload)
    return response.json()["id"]


async def update_parent(parent_id: int, patch: dict) -> None:
    await _request("PATCH", f"/v1/Parents/{parent_id}", json=patch)


async def deactivate_pupil(pupil_id: int, *, end_date: date | None = None,
                           reason: str = "", deactivate_parents: bool = False) -> None:
    body: dict[str, Any] = {"deactivateParents": deactivate_parents}
    if end_date:
        body["endDate"] = end_date.isoformat()
    if reason:
        body["reason"] = reason
    await _request("POST", f"/v1/Pupils/{pupil_id}/Deactivate", json=body)


async def activate_pupil(pupil_id: int, *, activate_parents: bool = False) -> None:
    await _request("POST", f"/v1/Pupils/{pupil_id}/Activate",
                   json={"activateParents": activate_parents})


# ---------------------------------------------------------------------------
# customData: злиття замість перезапису
# ---------------------------------------------------------------------------

def merge_custom_data(existing: Iterable[dict] | None,
                      updates: dict[str, str]) -> list[dict]:
    """Зливає наші значення з тим, що вже лежить на картці.

    Масив замінюється цілком, тому надіслати лише свої поля означає видалити
    чужі — насамперед «Ролі», які веде школа, і будь-яке поле, заведене після
    написання цього коду.

    Побічно схлопує дублікати: у 214 карток одне й те саме поле записане по
    кілька разів з однаковим значенням.
    """
    merged: dict[str, str] = {}
    for entry in existing or []:
        name = (entry.get("name") or "").strip()
        if name and name not in merged:
            merged[name] = entry.get("value") or ""
    for name, value in updates.items():
        merged[name.strip()] = value
    return [{"name": n, "value": v} for n, v in merged.items()]


# ---------------------------------------------------------------------------
# Мапінг Firestore -> SchoolToday
# ---------------------------------------------------------------------------

def normalize_nickname(value: str | None) -> str:
    """Нікнейми в базі записані по-різному — половина з '@', половина без."""
    value = (value or "").strip().lstrip("@")
    return f"@{value}" if value else ""


def _as_date(value: Any) -> str | None:
    if not value:
        return None
    if isinstance(value, str):
        return value[:10]
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m-%d")
    strftime = getattr(value, "strftime", None)  # Firestore Timestamp
    return strftime("%Y-%m-%d") if strftime else None


def _yes_no(value: Any) -> str:
    return "Так" if value else "Ні"


async def build_pupil_custom_data(doc: dict) -> dict[str, str]:
    """Значення кастомних полів учня, ключі — актуальні назви з довідника.

    Порожні значення пропускаємо: `{"name": "X", "value": ""}` видаляє поле, а
    порожнє й відсутнє значення в інтерфейсі виглядають однаково. Тож мовчазне
    затирання того, що вписала школа, коштувало б дорожче за неможливість
    очистити поле через бота.
    """
    registry = await get_registry()
    name = registry["field_name"]
    values = {
        "age_group": AGE_GROUP.get(doc.get("ageGroup"), ""),
        "health": _yes_no(doc.get("hasHealthIssues")),
        "health_details": doc.get("healthIssuesDetails") or "",
        "lead_source": doc.get("leadSource") or "",
        "tg_nickname": normalize_nickname(doc.get("telegramUsername")),
        "tg_id": str(doc.get("telegramId") or ""),
        "semester": doc.get("semester") or "",
        "idp": _yes_no(doc.get("isDisplaced")),
        "idp_region": doc.get("displacedRegion") or "",
    }
    return {name[alias]: values[alias] for alias in WRITABLE_FIELDS if values[alias]}


async def build_pupil_payload(doc_id: str, doc: dict, *,
                              existing: dict | None = None,
                              grant_access: bool | None = None) -> dict:
    """Тіло запиту для створення або оновлення учня.

    `existing` — картка з ШС, якщо вона вже є: з неї беремо поточний
    `customData`, щоб не стерти чужі поля.
    """
    registry = await get_registry()
    age_group = doc.get("ageGroup")

    payload: dict[str, Any] = {
        "externalID": doc_id,
        "firstName": (doc.get("firstName") or "").strip(),
        "lastName": (doc.get("lastName") or "").strip(),
        "birthday": _as_date(doc.get("birthDate")),
        "gender": GENDER.get(doc.get("gender")),
        "email": (doc.get("email") or "").strip().lower(),
        "isHidden": False,
        "customData": merge_custom_data(
            (existing or {}).get("customData"),
            await build_pupil_custom_data(doc),
        ),
    }

    class_name = CLASS_BY_AGE_GROUP.get(age_group)
    if class_name and class_name in registry["class_id"]:
        payload["classID"] = registry["class_id"][class_name]

    house = (doc.get("house") or "").strip()
    if house in registry["pupil_type_id"]:
        payload["pupilTypeID"] = registry["pupil_type_id"][house]

    address = ", ".join(p for p in ((doc.get("city") or "").strip(),
                                    (doc.get("country") or "").strip()) if p)
    if address:
        payload["address"] = address

    if grant_access is not None:
        payload["grantAccess"] = grant_access

    return payload


def parent_external_id(doc: dict) -> str | None:
    """Ключ батька з нормалізованого телефону. None — потрібен синтетичний."""
    phone = normalize_phone(doc.get("parentPhone"))
    return f"P-{phone.lstrip('+')}" if phone else None


def build_parent_payload(doc: dict, external_id: str, *,
                         grant_access: bool | None = None) -> dict:
    """Тіло запиту для батька.

    Поля `pupilIDs` тут немає навмисно — і не має з'явитись. Воно замінює набір
    дітей цілком, тож будь-яке значення відв'язало б інших дітей цієї людини.
    Зв'язок ставимо з боку учня через `parentIDs`.
    """
    payload: dict[str, Any] = {
        "externalID": external_id,
        "firstName": (doc.get("parentFirstName") or "").strip(),
        "lastName": (doc.get("parentLastName") or "").strip(),
        "email": (doc.get("parentEmail") or "").strip().lower(),
        "isHidden": False,
    }
    phone = normalize_phone(doc.get("parentPhone"))
    if phone:
        payload["phoneNumber"] = phone
    if grant_access is not None:
        payload["grantAccess"] = grant_access
    return payload


# ---------------------------------------------------------------------------
# Зарахування
# ---------------------------------------------------------------------------

# Унікальність externalID перевіряється на рівні застосунку ШС, без захисту від
# гонки. Замок серіалізує виклики в межах процесу; для кількох інстансів потрібен
# ordering key у Cloud Tasks або блокування у Firestore.
_locks: dict[str, asyncio.Lock] = {}


def _lock_for(key: str) -> asyncio.Lock:
    return _locks.setdefault(key, asyncio.Lock())


async def upsert_parent(doc: dict, external_id: str, *,
                        grant_access: bool | None = None) -> int:
    async with _lock_for(external_id):
        existing = await find_parent(external_id)
        payload = build_parent_payload(doc, external_id, grant_access=grant_access)
        if existing:
            await update_parent(existing["id"], payload)
            return existing["id"]
        return await create_parent(payload)


async def upsert_pupil(doc_id: str, doc: dict, *, parent_ids: list[int] | None = None,
                       grant_access: bool | None = None) -> int:
    async with _lock_for(doc_id):
        existing = await find_pupil(doc_id)
        payload = await build_pupil_payload(
            doc_id, doc, existing=existing, grant_access=grant_access
        )
        # None означає «не чіпати зв'язки»; порожній список зняв би всі, тому
        # ключ додаємо лише коли справді є що записати.
        if parent_ids:
            payload["parentIDs"] = parent_ids

        if existing:
            await update_pupil(existing["id"], payload)
            return existing["id"]
        return await create_pupil(payload)


async def enroll(doc_id: str, doc: dict) -> dict[str, int | None]:
    """Повне зарахування: картка батька, картка учня, зв'язок, доступи.

    Порядок саме такий, бо `grantAccess` для батька спрацьовує лише коли до нього
    вже прив'язано хоча б одного учня.
    """
    parent_id: int | None = None
    external_id = parent_external_id(doc)

    if external_id:
        parent_id = await upsert_parent(doc, external_id)
    elif doc.get("parentFirstName"):
        log.warning(
            "Учень %s: телефон батька %r не нормалізується, картку не створюємо",
            doc_id, doc.get("parentPhone"),
        )

    pupil_id = await upsert_pupil(
        doc_id, doc,
        parent_ids=[parent_id] if parent_id else None,
        grant_access=True,
    )

    if parent_id:
        # Окремим викликом, бо на момент створення дітей у батька ще не було.
        await update_parent(parent_id, {"grantAccess": True})

    return {"pupilId": pupil_id, "parentId": parent_id}
