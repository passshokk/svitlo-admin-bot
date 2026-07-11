from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from core import database as db
from bot import keyboards as kb
from core.context import student_ctx, user_roles_ctx
from bot.states import Registration

class LoadDataMiddleware(BaseMiddleware):
    """Глобальний мідлвейр: просто дістає дані з БД і кладе в контекст"""
    async def __call__(self, handler, event: TelegramObject, data: dict):
        user = None
        if event.message:
            user = event.message.from_user
        elif event.callback_query:
            user = event.callback_query.from_user

        if user:
            user_id = user.id
            student = await db.get_student_by_tg_id(user_id)
            
            s_token = student_ctx.set(student)
            r_token = user_roles_ctx.set(student['data'].get('roles', 'student') if student else "")
            
            try:
                return await handler(event, data)
            finally:
                student_ctx.reset(s_token)
                user_roles_ctx.reset(r_token)
                
        return await handler(event, data)


class RequireAuthMiddleware(BaseMiddleware):
    """Охоронець: пускає тільки тих, хто є в базі, інакше — фолбек"""
    async def __call__(self, handler, event: TelegramObject, data: dict):
        # Дістаємо студента з нашої кишені (БД вже не чіпаємо)
        student = student_ctx.get()
        
        if student:
            # Юзер авторизований — працює хендлер
            return await handler(event, data)
        else:
            # Юзера немає в базі - робимо фолбек і просимо email
            msg = event.message if isinstance(event, CallbackQuery) else event
            state = data.get("state")
            
            if isinstance(event, CallbackQuery):
                await event.answer()
                
            await state.set_state(Registration.waiting_email)
            await msg.answer("<b>Щоб користуватись повним функціоналом, синхронізуй акаунт</b>", parse_mode="HTML")
            await msg.answer("🔐 Напиши свою електронну пошту, яку ти вказував при реєстрації у SvitloSchool:", reply_markup=kb.get_cancel_kb())
            return

