# task_routes.py
import logging
from fastapi import APIRouter, Request, Response
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest
import core.database as db
import core.config as cfg
import core.schooltoday as schooltoday
from core.bot_init import bot
from core.utils import export_to_notion
from core.constants import REMINDER_1_MSG, REMINDER_2_MSG, LEAD_WELCOME_MSG
from bot import keyboards as kb
from bot.reg_funnel import render_registration_prompt

tasks_router = APIRouter(prefix="/tasks")

@tasks_router.post("/sla_check")
async def task_sla_check(request: Request):
    """
    Воркер Cloud Tasks: перевіряє статус тікета через 10 хвилин.
    """
    try:
        payload = await request.json()
        ticket_id = payload.get("ticket_id")
        category = payload.get("category", "Невідомо")
        
        if not ticket_id:
            return Response(status_code=400)

        ticket_data = await db.get_ticket(ticket_id)
        
        if ticket_data and ticket_data.get('status') == 'open':
            await bot.send_message(
                chat_id=cfg.CURATOR_GROUP_ID,
                text=(
                    f"<b>🚨 {cfg.MAIN_CURATOR_USERNAME} 🚨</b>\n"
                    f"Тікет <code>#{ticket_id:05}</code> [Категорія: {category}] висить 10 хв без відповіді!"
                ),
                parse_mode="HTML",
                reply_to_message_id=int(ticket_id)
            )
            
        return Response(status_code=200)

    except Exception as e:
        logging.error(f"SLA Task error: {e}")
        # Повертаємо 500, щоб Cloud Tasks спробував виконати запит повторно (Retry Policy)
        return Response(status_code=500)

@tasks_router.post("/export_notion")
async def task_export_notion(request: Request):
    try:
        payload = await request.json()
        await export_to_notion(payload)
        return Response(status_code=200)
    except Exception as e:
        logging.error(f"Notion Export Task error: {e}")
        return Response(status_code=500)
    
async def _report_enroll_failure(doc_id: str, student: dict, reason: str,
                                 permanent: bool) -> None:
    """Пише невдачу в журнал і одразу повідомляє кураторів.

    Без цього провалене зарахування помітне лише в логах, яких ніхто не читає
    в реальному часі — учень просто тихо не з'являється у школі.
    """
    name = f"{student.get('firstName', '')} {student.get('lastName', '')}".strip() or doc_id
    await db.db.collection("FailedEnrollments").document(doc_id).set({
        "studentId": doc_id,
        "studentName": name,
        "email": student.get("email", ""),
        "reason": reason,
        "permanent": permanent,
        "at": db.get_kyivtime_now(),
    })

    kind = "❌ <b>Зарахування не пройшло</b>" if permanent else "⚠️ <b>Зарахування впало</b>"
    tail = ("Потрібне втручання — автоматично повторюватись не буде."
            if permanent else "Спроба повториться автоматично.")
    try:
        await bot.send_message(
            cfg.CURATOR_GROUP_ID,
            f"{kind}\n\n"
            f"<b>Студент:</b> {name}\n"
            f"<b>Пошта:</b> {student.get('email') or '—'}\n"
            f"<b>ID:</b> <code>{doc_id}</code>\n\n"
            f"<b>Причина:</b> {reason}\n\n{tail}",
        )
    except Exception as exc:  # сповіщення не має ламати воркер
        logging.error("Не вдалося повідомити кураторів про %s: %s", doc_id, exc)


@tasks_router.post("/schooltoday_enroll")
async def task_schooltoday_enroll(request: Request):
    """Воркер Cloud Tasks: синхронізує зарахованого студента з SchoolToday.

    Код відповіді визначає, чи Cloud Tasks повторить спробу, тому постійні й
    тимчасові помилки треба розрізняти. `4xx` від SchoolToday — це «email вже
    зайнятий» або «некоректні дані»: повторення їх не виправить, тож віддаємо
    `200`, щоб задача не крутилась до вичерпання спроб. Усе інше — мережа,
    таймаути, `5xx` — повторюємо.
    """
    payload = await request.json()
    doc_id = payload["doc_id"]
    doc = await db.db.collection("Svitlo").document(doc_id).get()
    svitlo_data = doc.to_dict() or {}

    try:
        # enroll() робить усю послідовність: картка батька, картка учня,
        # зв'язок між ними і лист-запрошення учневі. Ідемпотентна за externalID,
        # тож повторна спроба Cloud Tasks не створить дубля.
        result = await schooltoday.enroll(doc_id, svitlo_data)
    except schooltoday.STError as exc:
        permanent = 400 <= exc.status < 500
        reason = f"{exc.status}: {', '.join(exc.codes) or exc.raw}"
        if exc.keys:
            reason += f" (поля: {', '.join(exc.keys)})"
        logging.error("SchoolToday enroll %s -> %s", doc_id, reason)
        await _report_enroll_failure(doc_id, svitlo_data, reason, permanent)
        return Response(status_code=200 if permanent else 500)
    except Exception as exc:
        logging.exception("SchoolToday enroll %s впало несподівано", doc_id)
        await _report_enroll_failure(doc_id, svitlo_data, str(exc), permanent=False)
        return Response(status_code=500)

    # Зберігаємо ID карток, щоб наступні оновлення йшли без зайвого пошуку
    await db.db.collection("Svitlo").document(doc_id).update({
        "stPupilId": result["pupilId"],
        "stParentId": result["parentId"],
    })
    # Успіх знімає попередню відмітку про невдачу, якщо вона була
    await db.db.collection("FailedEnrollments").document(doc_id).delete()
    return Response(status_code=200)

@tasks_router.post("/send_reminder")
async def task_send_reminder(request: Request):
    """
    Воркер Cloud Tasks: нагадування лідам, які натиснули "Хочу зареєструватись",
    але не завершили заявку — через 24г і 48г. Планується в
    bot/reg_funnel.py::process_auth_new_lead (лише для новостворених лідів).
    """
    try:
        payload = await request.json()
        doc_id = payload.get("doc_id")
        step = payload.get("step")

        if not doc_id or step not in (1, 2):
            return Response(status_code=400)

        doc_ref = db.db.collection('Svitlo').document(doc_id)
        doc = await doc_ref.get()
        if not doc.exists:
            return Response(status_code=200)

        data = doc.to_dict()

        # Лід уже пройшов далі особистих даних (правила, скан документа, зарахування,
        # блокування) — нагадування вже не на часі.
        if data.get("stage") not in ("lead", "personal_data"):
            return Response(status_code=200)

        # Це нагадування вже надсилалось раніше — захист від Cloud Tasks retry.
        if (data.get("followupStep") or 0) >= step:
            return Response(status_code=200)

        # Реєстрацію призупинено овнером — не турбуємо лідів новими нагадуваннями.
        if not await db.get_registration_open():
            return Response(status_code=200)

        telegram_id = data.get("telegramId")
        if not telegram_id:
            return Response(status_code=200)

        first_name = data.get("firstName") or ""
        greeting = f"Привіт, {first_name}!" if first_name else "Привіт!"
        text = (REMINDER_1_MSG if step == 1 else REMINDER_2_MSG).format(greeting=greeting)

        try:
            await bot.send_message(chat_id=telegram_id, text=text, parse_mode="HTML")
        except (TelegramForbiddenError, TelegramBadRequest) as e:
            # Юзер заблокував бота чи інша непоправна помилка — більше не пробуємо,
            # просто фіксуємо крок, щоб друге нагадування теж не намагалось надіслати.
            logging.warning(f"Reminder send failed for {doc_id} (tg={telegram_id}): {e}")
            await doc_ref.update({"followupStep": step})
            return Response(status_code=200)

        # Одразу після нагадування показуємо, де саме лід зупинився:
        # якщо він уже в FSM анкети — точне питання, інакше — вітання з кнопкою старту.
        fsm_doc = await db.db.collection("FSM_Sessions").document(str(telegram_id)).get()
        fsm_data = fsm_doc.to_dict() if fsm_doc.exists else {}
        fsm_state = fsm_data.get("state")

        if fsm_state:
            await render_registration_prompt(bot, telegram_id, fsm_state, fsm_data.get("data", {}))
        else:
            await bot.send_message(
                chat_id=telegram_id,
                text=LEAD_WELCOME_MSG,
                parse_mode="HTML",
                reply_markup=kb.get_start_registration_kb()
            )

        await doc_ref.update({"followupStep": step})
        return Response(status_code=200)

    except Exception as e:
        logging.error(f"Send Reminder Task error: {e}")
        return Response(status_code=500)

@tasks_router.post("/delete_messages")
async def task_delete_messages(request: Request):
    """Фонове видалення повідомлень без блокування вебхука"""
    payload = await request.json()
    chat_id = payload.get("chat_id")
    for msg_id in payload.get("message_ids", []):
        try:
            await bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except Exception as e:
            logging.warning(f"Не вдалося видалити повідомлення {msg_id}: {e}")
    return Response(status_code=200)