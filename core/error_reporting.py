# core/error_reporting.py
"""Загальне звітування про необроблені винятки в Telegram-адмінчат.

Раніше єдиним прецедентом такого звіту був _report_enroll_failure у
api/task_routes.py (лише для провалів SchoolToday). Тепер ADMIN_GROUP_ID
перестає отримувати заявки на розгляд (той флоу переїхав у Solar Panel) і
натомість стає каналом лише для помилок — цей модуль узагальнює той самий
патерн на будь-який виняток у боті.
"""
import logging
import time
import traceback

import core.config as cfg
from core.bot_init import bot
from core.utils import esc_html

# Telegram обрізає повідомлення на 4096 символів — беремо не голову тексту,
# а ХВІСТ: причина падіння в Python-трейсбеку лежить унизу, а не вгорі.
_MAX_MESSAGE_LEN = 3500

# Однаковий виняток (той самий тип + початок тексту) не спамить чат при
# кожному повторі — лише раз на це вікно.
_DEDUP_WINDOW_SECONDS = 300
# Захист від каскаду РІЗНИХ помилок (напр. Firestore ліг цілком) — не більше
# стількох повідомлень на годину, з одним підсумковим "ще N придушено".
_HOURLY_LIMIT = 20

_last_sent: dict[str, float] = {}
_hour_started_at = time.monotonic()
_hour_count = 0
_hour_suppressed = 0


def _dedup_key(exc: BaseException) -> str:
    return f"{type(exc).__module__}.{type(exc).__qualname__}:{str(exc)[:200]}"


def _should_send(key: str) -> bool:
    """Дедуплікація + погодинний ліміт. Побічний ефект: оновлює лічильники."""
    global _hour_started_at, _hour_count, _hour_suppressed

    now = time.monotonic()
    if now - _hour_started_at >= 3600:
        _hour_started_at = now
        _hour_count = 0
        _hour_suppressed = 0

    last = _last_sent.get(key)
    if last is not None and now - last < _DEDUP_WINDOW_SECONDS:
        return False

    if _hour_count >= _HOURLY_LIMIT:
        _hour_suppressed += 1
        return False

    _last_sent[key] = now
    _hour_count += 1
    return True


async def report_error(exc: BaseException, *, context: str = "") -> None:
    """Надсилає виняток у ADMIN_GROUP_ID. Ніколи не кидає — помилка в звітуванні
    про помилку не повинна каскадом ламати той самий обробник, що впав."""
    key = _dedup_key(exc)
    if not _should_send(key):
        return

    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    tb = tb[-_MAX_MESSAGE_LEN:]

    lines = ["🐞 <b>Необроблена помилка</b>"]
    if context:
        lines.append(f"<b>Контекст:</b> {esc_html(context)}")
    lines.append(f"<pre>{esc_html(tb)}</pre>")

    if _hour_suppressed:
        lines.append(f"\n<i>Придушено ще {_hour_suppressed} повідомлень цієї години (ліміт {_HOURLY_LIMIT}/год)</i>")

    try:
        await bot.send_message(cfg.ADMIN_GROUP_ID, "\n".join(lines), parse_mode="HTML")
    except Exception:
        logging.exception("Не вдалося надіслати звіт про помилку в ADMIN_GROUP_ID")
