# api/task_manager.py
import os
import json
from datetime import datetime, timedelta, timezone
from google.cloud import tasks_v2
from google.protobuf import timestamp_pb2
from google.api_core.retry import AsyncRetry
from google.api_core.exceptions import (
    ServiceUnavailable,
    DeadlineExceeded,
    InternalServerError,
    Aborted,
)

PROJECT_ID = "svitlo-auth-bot"
REGION = "europe-west3"
QUEUE_NAME = "bot-tasks-queue"

# Окрема черга під зарахування в SchoolToday, серіалізована в один потік.
#
# Загальна черга налаштована на 1000 одночасних задач — правильно для видалення
# повідомлень і нагадувань, але згубно для ШС: унікальність externalID там
# перевіряється на рівні застосунку, без захисту від гонки. Дві паралельні
# спроби для одного учня створили б дві картки. Плюс сплеск на сотні одночасних
# запитів майже напевно спіймає Cloudflare.
#
# Швидкість тут не потрібна: зарахування — фонова операція, і навіть тисячі
# студентів пройдуть чергою за години.
SCHOOLTODAY_QUEUE = "schooltoday-queue"

SERVICE_URL = os.getenv("SERVICE_URL")

# Cloud Tasks зрідка рве gRPC-стрім у момент create_task: у логах це
# "503 UNAVAILABLE: Stream removed (recvmsg:Connection reset by peer (104))",
# рідше DEADLINE_EXCEEDED / 500. Раніше такий збій летів необробленим
# винятком у webhook-хендлер (напр. process_auth_new_lead) і рвав воронку
# юзеру. Ретрай безпечний: імені таски ми не задаємо, тож у найгіршому разі
# буде дубль, а приймачі в api/task_routes самі відсіюють застарілі/повторні.
_CREATE_TASK_RETRY = AsyncRetry(
    predicate=lambda exc: isinstance(
        exc, (ServiceUnavailable, DeadlineExceeded, InternalServerError, Aborted)
    ),
    initial=0.5,
    maximum=8.0,
    multiplier=2.0,
    timeout=30.0,
)

_async_client: tasks_v2.CloudTasksAsyncClient | None = None

def _get_async_tasks_client() -> tasks_v2.CloudTasksAsyncClient:
    global _async_client
    if _async_client is None:
        # Використовуємо асинхронний клієнт SDK
        _async_client = tasks_v2.CloudTasksAsyncClient()
    return _async_client

async def enqueue_task(endpoint: str, payload: dict, delay_seconds: int = 0,
                       queue: str = QUEUE_NAME):
    """
    Відправляє таску в Cloud Tasks.
    endpoint: шлях (наприклад, '/tasks/sla_check')
    payload: словник з даними
    delay_seconds: затримка у секундах (0 = миттєво)
    queue: ім'я черги; для зарахувань — SCHOOLTODAY_QUEUE
    """
    if not SERVICE_URL:
        raise ValueError("SERVICE_URL is missing in environment variables.")

    client = _get_async_tasks_client()
    parent = client.queue_path(PROJECT_ID, REGION, queue)
    url = f"{SERVICE_URL.rstrip('/')}{endpoint}"

    task = {
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": url,
            "headers": {"Content-Type": "application/json"},
            # default=... — деякі payload'и (напр. тікет із Firestore) містять datetime,
            # який json.dumps сам не серіалізує; .isoformat() і рядок переживають
            # рейс-тріп через Cloud Tasks, де приймач розбирає їх назад (див. format_notion_date)
            "body": json.dumps(payload, default=lambda o: o.isoformat() if hasattr(o, "isoformat") else str(o)).encode(),
        }
    }

    if delay_seconds > 0:
        d = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)
        timestamp = timestamp_pb2.Timestamp()
        timestamp.FromDatetime(d)
        task["schedule_time"] = timestamp

    # Тепер create_task повертає асинхронний корутин-об'єкт
    await client.create_task(
        request={"parent": parent, "task": task},
        retry=_CREATE_TASK_RETRY,
    )