from aiogram.fsm.state import StatesGroup, State

class TicketFSM(StatesGroup):
    choosing_category = State()
    writing_first_message = State()

class Registration(StatesGroup):
    waiting_email = State()