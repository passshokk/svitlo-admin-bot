from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from context import user_roles_ctx

def get_start_menu() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="✅ Так, я вже є в чаті", callback_data="verify")],
        [InlineKeyboardButton(text="👨‍👩‍👦‍👦 Отримати доступ", callback_data="get_gengroup_access")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ==========================
# region --- Svitlo Menu

def get_main_menu() -> InlineKeyboardMarkup:
    roles_str = user_roles_ctx.get()
    roles_list = roles_str.split('|')
    
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

def get_cancel_kb() -> ReplyKeyboardMarkup:
    buttons = [[KeyboardButton(text="❌ Скасувати")]]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True, one_time_keyboard=True)

def get_notify_me_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔔 Нагадати мені", callback_data="notify_me"))
    return builder.as_markup()

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

def get_categories_kb() -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(text="Технічні баги")],
        [KeyboardButton(text="Освітній процес")],
        [KeyboardButton(text="Організаційні питання")],
        [KeyboardButton(text="❌ Скасувати")]
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