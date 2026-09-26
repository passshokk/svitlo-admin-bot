# core/age_promotion.py
"""Вікове переведення учнів: younger -> older.

Firestore — джерело істини. Це переведення робить рівно три речі:

  1. міняє `ageGroup` з "younger" на "older" тим зарахованим учням, кому вже
     виповнилось 14 (нативна вікова межа школи: молодша 10-13, старша 14-18);
  2. штовхає зміну в SchoolToday наявним однобічним синком — `core/sync_ops.py`
     уже вміє перекладати `ageGroup` -> `classID`, окремої інтеграції не треба;
  3. шле учневі повідомлення в бот з кнопкою «перейти в чат старшої групи»
     (саму дію — інвайт + кік з молодшого чату — робить bot/age_group.py, коли
     учень натисне кнопку).

Запускається ВРУЧНУ раз на семестр, перед Induction Week: або
`python -m scripts.promote_by_age --apply`, або кнопкою в Solar Panel
(`/admin/age-promotion/apply`). Крону під це свідомо немає — семестр короткий,
подія рідкісна, а список кандидатів однаково треба звірити очима.

Ідемпотентність безкоштовна: кандидати відбираються за `ageGroup == "younger"`,
тож після `--apply` вони випадають з вибірки — повторний прогін нікого не
переведе і не сповістить удруге.

Живе в `core/`, а не `scripts/`: цю ж функцію викликає прод-контейнер бота
через `api/admin_routes.py` (кнопка в панелі), а `scripts/` у деплой не їде
(.gcloudignore).
"""
import asyncio
import collections
import logging
from datetime import date

from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
)
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from core import config as cfg
from core.bot_init import bot
from core.constants import AGE_GROUP_MOVE_CB, AGE_PROMOTION_BUTTON, AGE_PROMOTION_MSG
from core.database import db, get_kyivtime_now
from core.utils import calculate_age, kyiv_today

log = logging.getLogger(__name__)

PROMOTE_AT_AGE = 14
OLDER_AGE_CEILING = 18          # понад це у молодшій групі — аномалія даних
TRANSFERS = "AgeGroupTransfers"  # журнал переведень (один документ на учня)
BATCH_SIZE = 400                 # ліміт Firestore — 500 операцій на батч
NOTIFY_RATE = 20                 # повідомлень на секунду (запас від ~30/с Telegram)
PREVIEW_ROWS = 50               # скільки рядків показувати в пробному прогоні


def _fmt_date(value) -> str:
    if not value:
        return "—"
    strftime = getattr(value, "strftime", None)
    return strftime("%d.%m.%Y") if strftime else str(value)[:10]


def _name(doc: dict) -> str:
    return f"{doc.get('firstName', '') or ''} {doc.get('lastName', '') or ''}".strip()


def select_promotable(docs: list[dict], today: date | None = None):
    """Розкладає документи на купи. `docs` — список dict з ключем `_id`.

    Повертає (promote, no_birthdate, anomalies):
      * promote      — [(doc, age)] younger + stage=student + вік >= 14;
      * no_birthdate — дату народження не розпарсити, переведення пропущено;
      * anomalies    — підмножина promote з віком > 18 (переводимо, але звірити).
    """
    today = today or kyiv_today()
    promote: list[tuple[dict, int]] = []
    no_birthdate: list[dict] = []
    anomalies: list[tuple[dict, int]] = []

    for doc in docs:
        if doc.get("ageGroup") != "younger" or doc.get("stage") != "student":
            continue
        age = calculate_age(doc.get("birthDate"), today)
        if age is None:
            no_birthdate.append(doc)
            continue
        if age < PROMOTE_AT_AGE:
            continue
        promote.append((doc, age))
        if age > OLDER_AGE_CEILING:
            anomalies.append((doc, age))

    return promote, no_birthdate, anomalies


def _move_keyboard(doc_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text=AGE_PROMOTION_BUTTON,
            callback_data=f"{AGE_GROUP_MOVE_CB}:{doc_id}",
        )
    ]])


async def _notify(doc_id: str, doc: dict) -> str:
    """'sent' / 'blocked' / 'no_tg' / 'failed'."""
    tg_id = doc.get("telegramId")
    if not tg_id:
        return "no_tg"
    text = AGE_PROMOTION_MSG.format(name=(doc.get("firstName") or "").strip() or "друже")
    while True:
        try:
            await bot.send_message(tg_id, text, reply_markup=_move_keyboard(doc_id))
            return "sent"
        except TelegramForbiddenError:
            return "blocked"
        except TelegramRetryAfter as exc:
            log.warning("Flood control, чекаю %sс", exc.retry_after)
            await asyncio.sleep(exc.retry_after)
        except (TelegramBadRequest, TelegramNetworkError) as exc:
            log.warning("Не вдалося сповістити %s (tg=%s): %s", doc_id, tg_id, exc)
            return "failed"


async def _record_transfer(doc_id: str, doc: dict, age: int, notified: bool) -> None:
    await db.collection(TRANSFERS).document(doc_id).set({
        "studentId": doc_id,
        "name": _name(doc),
        "from": "younger",
        "to": "older",
        "age": age,
        "birthDate": doc.get("birthDate"),
        "at": get_kyivtime_now(),
        "notified": notified,
        "chatMoved": False,       # ставить bot/age_group.py після натискання кнопки
        "syncedToST": False,      # ставить нижче після успішного синку
    })


async def run(*, apply: bool = False, notify: bool = True,
              trigger_sync: bool = True, limit: int | None = None) -> None:
    """Друкує звіт у stdout. Без `apply` — лише пробний прогін."""
    docs: list[dict] = []
    async for snap in db.collection("Svitlo").stream():
        data = snap.to_dict() or {}
        data["_id"] = snap.id
        docs.append(data)

    promote, no_birthdate, anomalies = select_promotable(docs)
    if limit:
        promote = promote[:limit]

    print("=" * 74)
    print(f"КАНДИДАТИ НА ПЕРЕВЕДЕННЯ younger -> older: {len(promote)}")
    print("=" * 74)
    for doc, age in promote[:PREVIEW_ROWS]:
        print(f"  {_name(doc):<32}  {age} р.  ДН {_fmt_date(doc.get('birthDate'))}  [{doc['_id']}]")
    if len(promote) > PREVIEW_ROWS:
        print(f"  … ще {len(promote) - PREVIEW_ROWS}")

    if anomalies:
        print(f"\n⚠ Вік > {OLDER_AGE_CEILING} у молодшій групі ({len(anomalies)}) — "
              f"переводимо, але звірте дані:")
        for doc, age in anomalies:
            print(f"    {_name(doc):<32}  {age} р.  [{doc['_id']}]")

    if no_birthdate:
        print(f"\n⚠ Без дати народження / не розпарсити ({len(no_birthdate)}) — пропущено:")
        for doc in no_birthdate[:PREVIEW_ROWS]:
            print(f"    {_name(doc):<32}  [{doc['_id']}]")
        if len(no_birthdate) > PREVIEW_ROWS:
            print(f"    … ще {len(no_birthdate) - PREVIEW_ROWS}")

    if not apply:
        print("\nПробний прогін. Щоб застосувати — додай --apply")
        return

    if not promote:
        print("\nНемає кого переводити.")
        return

    # --- 1. Firestore: ageGroup -> older ---
    now = get_kyivtime_now()
    for start in range(0, len(promote), BATCH_SIZE):
        batch = db.batch()
        for doc, _age in promote[start:start + BATCH_SIZE]:
            batch.update(
                db.collection("Svitlo").document(doc["_id"]),
                {"ageGroup": "older", "ageGroupPromotedAt": now},
            )
        await batch.commit()
    print(f"\nFirestore: переведено {len(promote)}")

    # --- 2. Сповіщення + журнал переведень ---
    counts: collections.Counter = collections.Counter()
    delay = 1 / NOTIFY_RATE if NOTIFY_RATE > 0 else 0
    for doc, age in promote:
        result = "skipped"
        if notify:
            result = await _notify(doc["_id"], doc)
            counts[result] += 1
            if delay:
                await asyncio.sleep(delay)
        await _record_transfer(doc["_id"], doc, age, notified=(result == "sent"))
    if notify:
        print(f"Сповіщення: надіслано {counts['sent']}, заблокували бота "
              f"{counts['blocked']}, без Telegram {counts['no_tg']}, помилок {counts['failed']}")

    # --- 3. Синк Firestore -> SchoolToday ---
    if trigger_sync:
        from core import drift_ops, sync_ops  # важкі імпорти лише коли справді треба
        print("\n" + "=" * 74)
        print("СИНХРОНІЗАЦІЯ Firestore -> SchoolToday")
        print("=" * 74)
        await sync_ops.main(["--apply"])

        for start in range(0, len(promote), BATCH_SIZE):
            batch = db.batch()
            for doc, _age in promote[start:start + BATCH_SIZE]:
                batch.set(db.collection(TRANSFERS).document(doc["_id"]),
                          {"syncedToST": True}, merge=True)
            await batch.commit()

        print("\n" + "=" * 74)
        print("DRIFT-РЕПОРТ ПІСЛЯ СИНКУ")
        print("=" * 74)
        await drift_ops.main([])

    # --- 4. Підсумок в адмінчат ---
    not_delivered = counts["blocked"] + counts["no_tg"] + counts["failed"]
    lines = [
        "🎂 <b>Вікове переведення виконано</b>",
        f"Переведено younger → older: <b>{len(promote)}</b>",
    ]
    if notify:
        lines.append(f"Сповіщено: {counts['sent']} · не дійшло: {not_delivered}")
    if anomalies:
        lines.append(f"⚠ Вік &gt; {OLDER_AGE_CEILING} (звірте дані): {len(anomalies)}")
    if no_birthdate:
        lines.append(f"⚠ Без дати народження, пропущено: {len(no_birthdate)}")
    if trigger_sync:
        lines.append("Синк у SchoolToday — виконано (див. drift-репорт у логах).")
    try:
        await bot.send_message(cfg.ADMIN_GROUP_ID, "\n".join(lines))
    except Exception as exc:  # підсумок не має валити операцію
        log.error("Не вдалося надіслати підсумок вікового переведення: %s", exc)
