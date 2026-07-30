from aiogram.fsm.state import StatesGroup, State

class TicketFSM(StatesGroup):
    choosing_category = State()
    writing_first_message = State()

class Registration(StatesGroup):
    waiting_email = State()

    # Нова лінійна воронка (Flat Schema)
    entering_first_name = State()
    entering_last_name = State()
    entering_gender = State()
    entering_dob = State()
    entering_email = State()
    entering_phone = State()

    entering_country = State()
    entering_city = State()
    entering_displaced_bool = State()
    entering_displaced_region = State()

    entering_parent_first_name = State()
    entering_parent_last_name = State()
    entering_parent_email = State()
    entering_parent_phone = State()

    entering_lead_source = State()
    entering_lead_source_details = State()
    entering_health_bool = State()
    entering_health_details = State()

    confirming_data = State()
    editing_field = State()
    
    passing_rules = State()
    uploading_docs = State()
    admin_review = State()