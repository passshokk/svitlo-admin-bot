from aiogram.fsm.state import StatesGroup, State

class TicketFSM(StatesGroup):
    choosing_category = State()
    writing_first_message = State()

class Registration(StatesGroup):
    waiting_email = State()

    # Нова лінійна воронка
    entering_full_name = State()
    entering_age = State()
    entering_email = State()
    entering_phone = State()
    passing_rules = State()
    uploading_docs = State()