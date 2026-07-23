from aiogram.fsm.state import StatesGroup, State

class TicketFSM(StatesGroup):
    choosing_category = State()
    writing_first_message = State()

class Registration(StatesGroup):
    waiting_email = State()

    # Нова лінійна воронка (Flat Schema)
    entering_first_name = State()
    entering_last_name = State()
    entering_email = State()
    entering_phone = State()
    entering_gender = State()
    entering_dob = State()
    entering_location = State()
    entering_school = State()

    entering_parent_name = State()
    entering_parent_email = State()
    entering_parent_phone = State()

    entering_lead_source = State()
    entering_health_bool = State()
    entering_health_details = State()
    
    passing_rules = State()
    uploading_docs = State()
    admin_review = State()