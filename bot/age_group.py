# bot/age_group.py
"""Кнопка «Перейти до чату старшої групи» під повідомленням вікового переведення.

Повідомлення розсилає core/age_promotion.py (масово, перед Induction Week).
Саму дію робить учень тут, натиснувши кнопку:

  * створюємо одноразове персональне посилання в чат старшої групи;
  * прибираємо учня з чату молодшої групи (ban + одразу unban, щоб за потреби
    міг повернутись — це не бан, а «викинути»).

Бот має бути адміном в обох чатах; у молодшому — з правом «Block users»
(`can_restrict_members`), інакше `ban_chat_member` впаде на нестачі прав.
"""
import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from core import config as cfg
from core import database as db
from core.bot_init import bot
from core.constants import (
    AGE_GROUP_MOVE_CB,
    AGE_PROMOTION_LINK_ONLY_MSG,
    AGE_PROMOTION_MOVED_MSG,
)
from core.error_reporting import report_error

log = logging.getLogger(__name__)

age_group_router = Router()
# Повідомлення вікового переведення приходить у приват; кнопка діє лише там.
age_group_router.callback_query.filter(F.message.chat.type == "private")

# Статуси, за яких людина реально в чаті (для "restricted" ще звіряємо is_member).
_PRESENT = {"member", "administrator", "creator", "restricted"}


@age_group_router.callback_query(F.data.startswith(f"{AGE_GROUP_MOVE_CB}:"))
async def on_age_group_move(cb: CallbackQuery) -> None:
    doc_id = cb.data.split(":", 1)[1]
    uid = cb.from_user.id

    snap = await db.db.collection("Svitlo").document(doc_id).get()
    data = snap.to_dict() if snap.exists else None
    if not data or data.get("telegramId") != uid:
        await cb.answer("Ця кнопка не для цього акаунта.", show_alert=True)
        return

    younger_id = cfg.GROUPS_MAPPING["younger"]
    older_id = cfg.GROUPS_MAPPING["older"]

    # Чи він у чаті молодшої групи — від цього залежить текст підтвердження.
    in_younger = False
    try:
        member = await bot.get_chat_member(younger_id, uid)
        in_younger = (
            getattr(member, "status", None) in _PRESENT
            and getattr(member, "is_member", True)
        )
    except TelegramBadRequest as exc:
        log.warning("agegrp: get_chat_member(%s) для %s: %s", younger_id, doc_id, exc)

    removed = False
    if in_younger:
        try:
            await bot.ban_chat_member(younger_id, uid)
            await bot.unban_chat_member(younger_id, uid, only_if_banned=True)
            removed = True
        except TelegramBadRequest as exc:
            log.warning("agegrp: кік %s з молодшої групи не вдався: %s", doc_id, exc)

    try:
        invite = await bot.create_chat_invite_link(older_id, member_limit=1)
    except TelegramBadRequest as exc:
        log.error("agegrp: інвайт у старшу групу для %s не створився: %s", doc_id, exc)
        await report_error(exc, context=f"age_group invite link ({doc_id})")
        await cb.answer(
            "Не вдалося створити посилання. Напиши /help — тобі допоможуть.",
            show_alert=True,
        )
        return

    # Прибираємо кнопку з початкового повідомлення, щоб її не тиснули повторно.
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass

    head = AGE_PROMOTION_MOVED_MSG if removed else AGE_PROMOTION_LINK_ONLY_MSG
    await bot.send_message(
        uid,
        head,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="💬 Відкрити чат старшої групи", url=invite.invite_link)
        ]]),
    )

    await db.db.collection("Svitlo").document(doc_id).update({"hasGroupAccess": True})
    try:
        await db.db.collection("AgeGroupTransfers").document(doc_id).set(
            {
                "chatMoved": True,
                "chatMovedAt": db.get_kyivtime_now(),
                "removedFromYounger": removed,
            },
            merge=True,
        )
    except Exception as exc:  # журнал вторинний — не ламаємо флоу
        log.warning("agegrp: не оновив журнал переведення для %s: %s", doc_id, exc)

    await cb.answer("Готово!")
