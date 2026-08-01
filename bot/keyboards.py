# bot/keyboards.py
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, Message, KeyboardButtonRequestUsers
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.types.web_app_info import WebAppInfo
import os

from core.context import user_roles_ctx

# ==========================
# region --- Registration

# --- profile data ---

def get_start_menu() -> InlineKeyboardMarkup:
    """Стартове меню для ідентифікованих студентів та випускників"""
    buttons = [
        [InlineKeyboardButton(text="✅ Так, я вже є в чаті", callback_data="verify")],
        [InlineKeyboardButton(text="👨‍👩‍👦‍👦 Отримати доступ", callback_data="get_gengroup_access")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_guest_start_menu() -> InlineKeyboardMarkup:
    """Стартове меню для неідентифікованих користувачів (лідів)"""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🎓 Я вже є студентом Svitlo", callback_data="auth_existing"))
    builder.row(InlineKeyboardButton(text="🙋 Хочу зареєструватись", style="primary", callback_data="auth_new_lead"))
    return builder.as_markup()

def get_start_registration_kb() -> InlineKeyboardMarkup:
    """Кнопка для переходу від вітального повідомлення до збору даних"""
    buttons = [[InlineKeyboardButton(text="🚀 Розпочати реєстрацію", style="danger", callback_data="start_onboarding_flow")]]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_number_for_registration_kb() -> ReplyKeyboardMarkup:
    """Кнопка для швидкої відправки номера телефону"""
    buttons = [
        [KeyboardButton(text="📱 Поділитись номером",style="success", request_contact=True)]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True, one_time_keyboard=True)

def get_gender_kb() -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(text="Чоловіча"), KeyboardButton(text="Жіноча")],
        [KeyboardButton(text="Волію не вказувати")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True, one_time_keyboard=True)

def get_lead_source_kb() -> ReplyKeyboardMarkup:
    """Клавіатура для джерел трафіку"""
    buttons = [
        [KeyboardButton(text="Школа"), KeyboardButton(text="Організація")],
        [KeyboardButton(text="Instagram"), KeyboardButton(text="TikTok")],
        [KeyboardButton(text="Від друзів"), KeyboardButton(text="Від батьків")],
        [KeyboardButton(text="Telegram-канал"), KeyboardButton(text="Facebook")],
        [KeyboardButton(text="Google"), KeyboardButton(text="ШІ"), KeyboardButton(text="Інше")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True, one_time_keyboard=True)

def get_boolean_kb(yes_text="Так", no_text="Ні") -> ReplyKeyboardMarkup:
    buttons = [[KeyboardButton(text=yes_text), KeyboardButton(text=no_text)]]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True, one_time_keyboard=True)

def get_data_confirmation_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Все правильно, йдемо далі", callback_data="confirm_data_success", style="success")
    builder.button(text="✍️ Змінити певні дані", callback_data="confirm_data_edit", style="primary")
    builder.adjust(1)
    return builder.as_markup()

def get_edit_fields_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="👤 Ім'я", callback_data="edit_field:firstName")
    builder.button(text="👤 Прізвище", callback_data="edit_field:lastName")
    builder.button(text="📅 ДН", callback_data="edit_field:birthDate")
    builder.button(text="📧 Email", callback_data="edit_field:email")
    builder.button(text="🌍 Країна", callback_data="edit_field:country")
    builder.button(text="📍 Місто", callback_data="edit_field:city")
    builder.button(text="🔙 Назад", callback_data="edit_field:cancel")
    builder.adjust(2, 2, 2, 1)
    return builder.as_markup()  

# --- rules & quiz ---

def get_rules_start_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📗 Ознайомитися з правилами", callback_data="rules_start")
    return builder.as_markup()

def get_quiz_start_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Прочитано. Почати квіз!", callback_data="quiz_start")
    return builder.as_markup()

def get_quiz_kb(options: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for i, opt in enumerate(options):
        builder.button(text=opt, callback_data=f"ans_{i}")
    builder.adjust(1)
    return builder.as_markup()

# --- ID check ---

def get_scanner_webapp_kb() -> InlineKeyboardMarkup:
    webapp_url = os.getenv("WEBAPP_URL")
    
    builder = InlineKeyboardBuilder()
    builder.button(
        text="📸 Сканувати документ", 
        web_app=WebAppInfo(url=webapp_url)
    )
    return builder.as_markup()

# --- admin review ---

def get_admin_action_kb(doc_id: str, tg_username: str, include_details_btn: bool = False) -> InlineKeyboardMarkup:
    """Генерує клавіатуру для кураторів (для нових лідів або розгорнутої анкети)"""
    builder = InlineKeyboardBuilder()
    
    if include_details_btn:
        builder.button(text="🔍 Розгорнути анкету", callback_data=f"lead_details_{doc_id}")
        
    if tg_username:
        builder.button(text="💬 Зв'язатися", url=f"https://t.me/{tg_username}")
    else:
        builder.button(text="💬 Зв'язатися (За номером)", callback_data="hidden_profile_alert")
        
    builder.button(text="⛔️ Відхилити", callback_data=f"lead_confirmblock_{doc_id}")
    builder.button(text="✅ Зарахувати (SchoolToday)", callback_data=f"lead_approve_{doc_id}")
    
    builder.adjust(1)
    return builder.as_markup()

def get_admin_confirm_block_kb(doc_id: str) -> InlineKeyboardMarkup:
    """Клавіатура підтвердження видалення ліда (захист від міскліку)"""
    builder = InlineKeyboardBuilder()
    builder.button(text="⚠️ Так, точно відхилити", callback_data=f"lead_block_{doc_id}")
    builder.button(text="🔙 Скасувати", callback_data=f"lead_details_{doc_id}")
    
    builder.adjust(1)
    return builder.as_markup()

# --- fallback ---

def get_registration_cancel_confirm() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="▶️ Продовжити реєстрацію", callback_data="reg_resume")],
        [InlineKeyboardButton(text="❌ Скасувати та пройти наново", callback_data="reg_restart")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# endregion
# ==========================
# region --- /menu

def get_main_menu() -> InlineKeyboardMarkup:
    roles_list = user_roles_ctx.get()
    
    builder = InlineKeyboardBuilder()
    builder.button(text="🎓 Your Svitlo Profile", callback_data="my_profile")
    builder.button(text="🏰 Join House Group", callback_data="house")
    builder.button(text="📚 Reading Buddy Groups", callback_data="rb_day:0")
    builder.button(text="👥 Connect with Prefects", callback_data="pref_group")
    builder.button(text="📱 Socials", callback_data="socials")
    builder.button(text="🆘 FAQ", url="https://telegra.ph/FAQ-Everything-about-Svitlo-School-04-10")
    builder.button(text="🌟 Svitlo Help Centre", callback_data="support_menu")
    builder.button(text="💌 Mental Support", url="https://forms.gle/MGyGav2krG1x7x8DA")
        
    builder.adjust(1, 1, 1, 1, 2, 1, 1)
    return builder.as_markup()

def get_socials_kb() -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text="📌 Svitlo Telegram Channel", url="https://t.me/svitloschool")
        ],
        [
            InlineKeyboardButton(text="📸 Instagram", url="https://instagram.com/svitloschool?igshid=YmMyMTA2M2Y="),
            InlineKeyboardButton(text="💙 Facebook", url="https://www.facebook.com/SvitioEducationUkr/")
        ],
        [
            InlineKeyboardButton(text="🎵 TikTok", url="https://www.tiktok.com/@svitloschool?t=8lKtAgogEwn&r=1"),
            InlineKeyboardButton(text="🎬 YouTube", url="https://www.youtube.com/@SvitloSchool/featured")
        ],
        [
            InlineKeyboardButton(text="✨ Сайт", url="https://svitloschool.com/"),
            InlineKeyboardButton(text="📝 Блог учнів", url="https://www.svitloschool.com/uk/school-life/student-blog")
        ],
        [
            InlineKeyboardButton(text="📰 Газета", url="https://www.svitloschool.com/uk/school-life/newsletter"),
            InlineKeyboardButton(text="💼 LinkedIn", url="https://uk.linkedin.com/company/svitlo-education")
        ],
        [
            InlineKeyboardButton(text="🧠 Strengths & Virtues Channel", url="https://t.me/personalstrengths_virtues")
        ],
        [
            InlineKeyboardButton(text="🔙 Назад у меню", callback_data="main_menu")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_back_to_menu_kb() -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton(text="🔙 Назад у меню", callback_data="main_menu")]]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_help_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="Зв'язатися з куратором", url="https://t.me/passshokk")],
        [InlineKeyboardButton(text="🔙 Назад у меню", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# endregion
# ==========================
# region --- Operational Buttons

async def drop_reply_keyboard(message: Message) -> None:
    """Миттєво збиває будь-яку застарілу Reply-клавіатуру з екрана клієнта Telegram."""
    tmp = await message.answer("🔄", reply_markup=ReplyKeyboardRemove())
    await tmp.delete()

def get_email_cancel_kb() -> ReplyKeyboardMarkup:
    buttons = [[KeyboardButton(text="🚫 Скасувати введення")]]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True, one_time_keyboard=True)

def get_pasha_curator_keyboard() -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton(text="Зв'язатися з куратором", url="https://t.me/passshokk")]]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_sasha_curator_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="Зв'язатися з хаус-кураторкою", url="https://t.me/sashkclt")],
        [InlineKeyboardButton(text="🔙 Назад у меню", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# endregion
# ==========================
# region --- Ticket System

def get_ticket_cancel_kb() -> ReplyKeyboardMarkup:
    buttons = [[KeyboardButton(text="🔙 Назад у меню")]]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True, one_time_keyboard=True)

def get_categories_kb() -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(text="Технічні баги")],
        [KeyboardButton(text="Освітній процес")],
        [KeyboardButton(text="Організаційні питання")],
        [KeyboardButton(text="🔙 Назад у меню")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def get_take_ticket_kb(ticket_id: str) -> InlineKeyboardMarkup:
    """Клавіатура, коли тікет відкритий"""
    buttons = [
        [InlineKeyboardButton(text="🙋‍♂️ Взяти в роботу", callback_data=f"take_{ticket_id}")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_taken_ticket_kb(ticket_id: str, curator_name: str) -> InlineKeyboardMarkup:
    """Клавіатура, коли тікет в роботі"""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=f"🔒 У роботі: {curator_name}", callback_data="noop")) # noop - no operation
    builder.row(InlineKeyboardButton(text="⛔️ Закрити тікет", callback_data=f"close_{ticket_id}"))
    return builder.as_markup()

def get_closed_ticket_kb(curator_name: str) -> InlineKeyboardMarkup:
    """Клавіатура, коли тікет вже закрито"""
    buttons = [
        [InlineKeyboardButton(text=f"✅ Закрито: {curator_name}", callback_data="noop")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_nps_kb(ticket_id: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for i in range(1, 6):
        builder.button(text=f"{i} ⭐", callback_data=f"nps_{ticket_id}_{i}")
    builder.adjust(5)
    return builder.as_markup()

# endregion
# ==========================
# region --- Dev Access Control
# ==========================

def get_user_picker_kb(request_id: int) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(
            text="👤 Обрати користувача",
            request_users=KeyboardButtonRequestUsers(request_id=request_id, max_quantity=1, user_is_bot=False, request_username=True)
        )]],
        resize_keyboard=True,
        one_time_keyboard=True
    )
