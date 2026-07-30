# bot/middleware.py
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from core import database as db
from core.context import student_ctx, user_roles_ctx
from bot.states import Registration
from aiogram.fsm.context import FSMContext

class LoadDataMiddleware(BaseMiddleware):
    """
    Глобальний мідлвейр: пошук користувача в БД за полем telegramId.
    Якщо stage = 'blocked' -> блокування.
    """
    async def __call__(self, handler, event: TelegramObject, data: dict):
        user = None
        if event.message:
            user = event.message.from_user
        elif event.callback_query:
            user = event.callback_query.from_user

        if user:
            student = await db.get_student_by_tg_id(user.id)
            
            # ⛔️ БЛОК: якщо stage == 'blocked'
            if student and student['data'].get('stage') == 'blocked':
                # Повертаємо None без виклику handler(), повністю ігноруючи подальші дії
                return

            s_token = student_ctx.set(student)
            roles = student['data'].get('roles', []) if student else []
            r_token = user_roles_ctx.set(roles)
            
            try:
                return await handler(event, data)
            finally:
                student_ctx.reset(s_token)
                user_roles_ctx.reset(r_token)
                
        return await handler(event, data)


class RequireAuthMiddleware(BaseMiddleware):
    """
    Фільтрує доступ до приватних роутерів.
    Невідомих юзерів відправляє на синхронізацію пошти.
    Лідів (у процесі реєстрації) — блокує.
    """
    async def __call__(self, handler, event: TelegramObject, data: dict):
        student = student_ctx.get()
        user_roles = user_roles_ctx.get()
        
        # 1. Юзера взагалі немає в базі -> Фолбек на синхронізацію
        if not student:
            return await self._prompt_sync(event, data)

        student_data = dict(student.get('data', {}))
        stage = student_data.get('stage')

        # 2. Перевірка доступу (Студенти + Ролі)
        allowed_stages = ['student', 'alumni']
        allowed_roles = ['boss', 'teacher']

        is_student = stage in allowed_stages
        is_roles = any(role in user_roles for role in allowed_roles)

        if is_student or is_roles:
            return await handler(event, data)
        
        # 3. Юзер є в базі, але він ще лід/на етапі реєстрації -> Заборона
        return await self._reject_access(event)

    async def _prompt_sync(self, event: TelegramObject, data: dict):
        """Хендлер для неідентифікованих (Просимо email)"""
        state: FSMContext = data.get("state")
        await state.set_state(Registration.waiting_email)

        trigger = event.data if isinstance(event, CallbackQuery) else getattr(event, "text", None)
        await state.update_data(email_flow_source="middleware_auto_prompt", triggered_by=trigger)

        text_1 = "<b>🔐 Щоб користуватись повним функціоналом, синхронізуй акаунт</b>"
        text_2 = "Напиши свою <b>електронну пошту</b>, яку ти вказував при реєстрації у SvitloSchool:"

        if isinstance(event, CallbackQuery):
            await event.answer()
            await event.message.edit_text(text_1, parse_mode="HTML")
            await event.message.answer(text_2, parse_mode="HTML")
        elif isinstance(event, Message):
            await event.answer(text_1, parse_mode="HTML")
            await event.answer(text_2, parse_mode="HTML")
            
        return

    async def _reject_access(self, event: TelegramObject):
        """Хендлер для лідів, які ще не завершили реєстрацію"""
        if isinstance(event, Message):
            await event.answer("⚠️ <b>Доступ лише для діючих студентів.</b>\nБудь ласка, заверши процес реєстрації", parse_mode="HTML")
        elif isinstance(event, CallbackQuery):
            await event.answer("⚠️ Доступ лише для діючих студентів. Будь ласка, заверши реєстрацію", show_alert=True)
        return