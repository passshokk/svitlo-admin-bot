# task_manager.py
import os
import json
import asyncio
from datetime import datetime, timedelta, timezone
from google.cloud import tasks_v2
from google.protobuf import timestamp_pb2

PROJECT_ID = "svitlo-auth-bot"
REGION = "europe-west3"
QUEUE_NAME = "bot-tasks-queue"

SERVICE_URL = os.getenv("SERVICE_URL") 

# Зберігаємо клієнт як глобальну змінну, але ініціалізуємо ліниво
_client: tasks_v2.CloudTasksClient | None = None

def _get_tasks_client() -> tasks_v2.CloudTasksClient:
    global _client
    if _client is None:
        # Ініціалізація відбудеться лише при першому виклику таски (не на старті контейнера)
        _client = tasks_v2.CloudTasksClient()
    return _client

async def enqueue_task(endpoint: str, payload: dict, delay_seconds: int = 0):
    """
    Відправляє таску в Cloud Tasks.
    endpoint: шлях (наприклад, '/tasks/sla_check')
    payload: словник з даними
    delay_seconds: затримка у секундах (0 = миттєво)
    """
    if not SERVICE_URL:
        raise ValueError("SERVICE_URL is missing in environment variables.")

    client = _get_tasks_client()
    parent = client.queue_path(PROJECT_ID, REGION, QUEUE_NAME)
    url = f"{SERVICE_URL.rstrip('/')}{endpoint}"

    task = {
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": url,
            "headers": {"Content-type": "application/json"},
            "body": json.dumps(payload).encode(),
        }
    }

    if delay_seconds > 0:
        d = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)
        timestamp = timestamp_pb2.Timestamp()
        timestamp.FromDatetime(d)
        task["schedule_time"] = timestamp

    # CloudTasksClient є синхронним, тому обгортаємо в to_thread
    await asyncio.to_thread(
        client.create_task, 
        request={"parent": parent, "task": task}
    )