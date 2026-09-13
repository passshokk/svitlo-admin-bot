from aiogram.filters import BaseFilter
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from core import config as cfg
from core import database as db

class IsTesterFilter(BaseFilter):
    """Пускає тестувальників. Список ID тягнеться з Firestore (Config/bot_settings.testers),
    тож додавання нового тестувальника не потребує редеплою коду.

    OWNER_ID пускається завжди, незалежно від вмісту Firestore: інакше власник,
    прибравши себе зі списку тестувальників (наприклад, помилково або тестуючи
    /testers), сам собі закриває доступ і до всього tester_router, включно з
    /testers — командою, якою це можна було б виправити."""
    async def __call__(self, event: Message | CallbackQuery) -> bool:
        if event.from_user.id == cfg.OWNER_ID:
            return True
        return event.from_user.id in await db.get_tester_ids()

class ActiveTicketFilter(BaseFilter):
    async def __call__(self, message: Message, state: FSMContext) -> bool | dict:
        # 1. Якщо юзер в процесі реєстрації або іншому FSM - ігноруємо
        if await state.get_state() is not None:
            return False
        
        # 2. Перевіряємо наявність тікета в БД
        active_ticket = await db.get_active_ticket(message.from_user.id)
        if active_ticket:
            # Повертаємо словник - aiogram автоматично прокине active_ticket як аргумент у хендлер
            return {"active_ticket": active_ticket}
        
        # 3. Якщо тікета немає - повідомлення летить далі вниз по роутерах
        return False