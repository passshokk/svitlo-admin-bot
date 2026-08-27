# api/admin_routes.py
"""Ручні операції синку для owner-панелі (svitlo_admin_panel).

Панель не дублює логіку core/sync_ops.py та core/drift_ops.py — вона лише
викликає ЦІ ендпоінти з X-Admin-Secret, а бот запускає ту саму логіку, що й
`python -m scripts.sync_to_schooltoday`/`drift_report` з консолі, і повертає
її stdout текстом. Це той самий принцип, що й з Cloud Tasks-чергою
зарахування: одне джерело правди для роботи зі SchoolToday лишається в
svitlo_admin_bot. Логіка живе в `core/`, а не в `scripts/`, саме тому, що її
тепер викликає й прод-контейнер бота — `scripts/` навмисно виключений з
деплою (.gcloudignore) і імпортувати звідти тут не можна.
"""
import io
import logging
import os
from contextlib import redirect_stdout

from fastapi import APIRouter, Header, HTTPException

from core import schooltoday
from core import drift_ops, sync_ops
from core.error_reporting import report_error

ADMIN_PANEL_SECRET = os.getenv("ADMIN_PANEL_SECRET")
if not ADMIN_PANEL_SECRET:
    raise ValueError("ADMIN_PANEL_SECRET is missing in environment variables")

admin_router = APIRouter(prefix="/admin")


def _check_secret(x_admin_secret: str | None) -> None:
    if x_admin_secret != ADMIN_PANEL_SECRET:
        logging.warning("Unauthorized /admin access attempt")
        raise HTTPException(status_code=401, detail="Unauthorized")


async def _run_captured(coro_factory, *, context: str) -> dict:
    """Ганяє скрипт-функцію, ловить її stdout, і не губить те, що вона встигла
    надрукувати, навіть якщо вона впала на середині (найкорисніше саме тоді:
    людина в панелі бачить, на якому записі зупинився `--apply`)."""
    # Довідник кастомних полів кешується на весь процес бота (core/schooltoday.py).
    # Якщо школа щось поміняла в налаштуваннях між деплоями — ці ручні виклики
    # мають бачити актуальний стан, а не кеш, що встиг протухнути роками роботи.
    schooltoday.reset_registry()

    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            await coro_factory()
    except Exception as exc:
        logging.exception("Admin sync tool failed: %s", context)
        await report_error(exc, context=f"admin_routes: {context}")
        return {"output": buf.getvalue(), "error": str(exc)}
    return {"output": buf.getvalue(), "error": None}


@admin_router.post("/sync/drift")
async def sync_drift(x_admin_secret: str | None = Header(default=None)):
    _check_secret(x_admin_secret)
    return await _run_captured(lambda: drift_ops.main([]), context="drift_report")


@admin_router.post("/sync/preview")
async def sync_preview(x_admin_secret: str | None = Header(default=None)):
    _check_secret(x_admin_secret)
    return await _run_captured(lambda: sync_ops.main([]), context="sync_preview")


@admin_router.post("/sync/apply")
async def sync_apply(x_admin_secret: str | None = Header(default=None)):
    _check_secret(x_admin_secret)
    return await _run_captured(lambda: sync_ops.main(["--apply"]), context="sync_apply")
