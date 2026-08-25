# bot/reg_funnel.py
from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove, InputMediaPhoto
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest
from google.cloud import firestore
import asyncio
import re
from datetime import datetime, timezone

from core import database as db
from core.database import db as firestore_client
from bot import keyboards as kb
from core import utils as ut
from bot.states import Registration, TicketFSM
from core.constants import QUIZ_DATA, LEAD_WELCOME_MSG, LEAD_INTERLUDE_1_MSG, RULES_MSG, LEAD_INTERLUDE_2_MSG, SCANNER_MSG, APPLICATION_CONFIRMED_MSG
from core.context import student_ctx
from api.task_manager import enqueue_task, SCHOOLTODAY_QUEUE
from core.config import EMAIL_REGEX, ENG_NAME_REGEX, UKR_REGEX
from core import config as cfg
from bot.filters import IsTesterFilter

# ===============================================================
# region CONSTANTS
# ===============================================================

EDIT_FIELD_PROMPTS = {
    "firstName": "Введи нове <b>ім'я</b> (англійською):",
    "lastName": "Введи нове <b>прізвище</b> (англійською):",
    "birthDate": "Введи нову <b>дату народження</b> (ДД.ММ.РРРР):",
    "email": "Введи новий <b>Email</b>:",
    "country": "Введи нову <b>країну</b> проживання:",
    "city": "Введи нове <b>місто</b> проживання:"
}

GENDER_HINT_CAPTION = "👀 Підказка: для деяких запитань використовуйте вбудовані кнопки вибору. Як їх знайти, дивіться на фото"
GENDER_HINT_FILE_ID_1 = "AgACAgIAAxUHanx6ZBQhWOanzGRQObHeF91bfnoAAgEaaxtuE-FLOy7CJsf3VrwBAAMCAAN5AAM9BA"
GENDER_HINT_FILE_ID_2 = "AgACAgIAAxUHanx6ZAKyROvHuJ_OyDkfEoT2hMwAAgIaaxtuE-FLWxV5Q02_a-cBAAMCAAN5AAM9BA"

def _replykb_hint() -> list[InputMediaPhoto]:
    return [
        InputMediaPhoto(media=GENDER_HINT_FILE_ID_1),
        InputMediaPhoto(media=GENDER_HINT_FILE_ID_2, caption=GENDER_HINT_CAPTION),
    ]

LEAD_SOURCE_DETAILS_PROMPTS = {
    "Інше": "Будь ласка, коротко уточни звідки чи від кого:",
    "Організація": "Будь ласка, уточни назву організації:",
}

# SSoT для тексту і клавіатур кожного кроку анкети. In _prompt(), in render_registration_prompt()
REGISTRATION_PROMPTS = {
    Registration.waiting_email.state: (
        "Напиши свою <b>електронну пошту</b>, яку ти вказував(-ла) при реєстрації у SvitloSchool:", None,
    ),
    Registration.entering_first_name.state: ("Будь ласка, введи своє <b>ім'я</b> (англійською):", None),
    Registration.entering_last_name.state: ("Яке твоє <b>прізвище</b> (англійською)?", None),
    Registration.entering_gender.state: ("Обери свою <b>стать</b>:", kb.get_gender_kb),
    Registration.entering_dob.state: (
        "Введи свою <b>дату народження</b> у форматі ДД.ММ.РРРР (наприклад: 24.08.2011):", None,
    ),
    Registration.entering_email.state: ("Яка твоя <b>електронна пошта</b> (та, якою найчастіше користуєшся)? На неї ми створимо акаунт у SvitloSchool", None),
    # Живий флоу шле це двома окремими повідомленнями (коротке питання + інструкція з кнопкою) —
    # тут навмисно один об'єднаний текст, тому що для resume-контексту зайве повідомлення не потрібне.
    Registration.entering_phone.state: (
        "Щоб поділитись <b>номером телефону</b>, натисни кнопку «Поділитись номером» нижче ↘️",
        kb.get_number_for_registration_kb,
    ),
    Registration.entering_country.state: ("<b>У якій країні</b> ти зараз проживаєш?", None),
    Registration.entering_city.state: ("Вкажи назву <b>міста чи села</b>, де ти зараз мешкаєш:", None),
    Registration.entering_displaced_bool.state: (
        "<b>Чи довелося тобі змінити місце проживання через війну? 🕊</b>\n\n"
        "<blockquote>ℹ️ Ця інформація допомагає нам підтримувати студентів та адаптовувати навчальні програми</blockquote>",
        kb.get_boolean_kb,
    ),
    Registration.entering_displaced_region.state: ("<b>З якої області України ти переїхав(-ла)?</b>", None),
    Registration.entering_parent_first_name.state: ("Вкажи <b>ім'я одного з батьків/опікунів</b>:", None),
    Registration.entering_parent_last_name.state: ("Вкажи <b>прізвище одного з батьків/опікунів</b>:", None),
    Registration.entering_parent_email.state: (
        "Яка <b>електронна пошта в одного з твоїх батьків/опікунів?</b>", None,
    ),
    Registration.entering_parent_phone.state: (
        "І який <b>номер телефону в одного з твоїх батьків/опікунів?</b> "
        "Вкажи у міжнародному форматі (наприклад, +380...)", None,
    ),
    Registration.entering_lead_source.state: (
        "<b>Звідки ти дізнався(-лась) про Svitlo School?</b> Обери або напиши свій варіант:",
        kb.get_lead_source_kb,
    ),
    Registration.entering_health_bool.state: (
        "І наостанок: чи є у тебе особливі потреби, пов'язані зі станом здоров'я або інвалідністю, про які нам "
        "варто знати для твоєї найкращої підтримки в Svitlo School? Наприклад, медичні застереження, потреби "
        "в адаптації матеріалів чи забезпеченні доступності",
        kb.get_boolean_kb,
    ),
    Registration.entering_health_details.state: (
        "Будь ласка, опиши їх коротко (це важливо, аби могли забезпечити інклюзивне середовище):", None,
    ),
    Registration.uploading_docs.state: (SCANNER_MSG, kb.get_scanner_webapp_kb),
    Registration.admin_review.state: ("⏳ Твоя заявка зараз перевіряється куратором. Зачекай результату", None),
}

def _prompt(state) -> str:
    """Текст питання для стану анкети — щоб не дублювати рядки в per-step хендлерах нижче"""
    return REGISTRATION_PROMPTS[state.state][0]

# endregion =====================================================
# region ROUTERS
# ===============================================================

reg_router = Router()
# Дозволяємо приватні чати (воронка реєстрації) та групу ADMIN_GROUP_ID (дії кураторів з анкетами).
reg_router.message.filter((F.chat.type == "private") | (F.chat.id == cfg.ADMIN_GROUP_ID))
reg_router.callback_query.filter((F.message.chat.type == "private") | (F.message.chat.id == cfg.ADMIN_GROUP_ID))

# endregion =====================================================
# region INTERCEPTORS
# ===============================================================

# --- 1. Інтерцептор команд під час реєстрації ---
@reg_router.message(StateFilter(Registration), ~StateFilter(Registration.waiting_email), Command("start", "menu", "profile", "house"))
async def cmd_during_registration(message: Message, state: FSMContext):
    await message.answer(
        "<b>⚠️ Ти перебуваєш в процесі реєстрації до Svitlo School!</b>\n\n"
        "Якщо ти вийдеш зараз, <b>заповнені дані не збережуться</b>, а доступ до функцій бота буде обмежено до завершення воронки",
        parse_mode="HTML",
        reply_markup=kb.get_registration_cancel_confirm()
    )
    await state.update_data(interruptMsgId=message.message_id)


@reg_router.callback_query(F.data == "reg_resume")
async def process_reg_resume(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    interrupt_msg_id = data.get("interruptMsgId")

    if interrupt_msg_id:
        try:
            await callback.bot.delete_message(callback.message.chat.id, interrupt_msg_id)
        except TelegramBadRequest:
            pass

    await callback.message.delete()
    await state.update_data(interruptMsgId=None)

@reg_router.callback_query(F.data == "reg_restart")
async def process_reg_restart(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    student = student_ctx.get()
    if not student:
        student = await db.get_student_by_tg_id(callback.from_user.id)
    if student:
        await db.update_crm_stage(student['id'], "lead")

    data = await state.get_data()
    interrupt_msg_id = data.get("interruptMsgId")

    if interrupt_msg_id:
        try:
            await callback.bot.delete_message(callback.message.chat.id, interrupt_msg_id)
        except TelegramBadRequest:
            pass

    await state.clear()
    await callback.message.delete()
    await state.update_data(interruptMsgId=None)
    await callback.message.answer("Реєстрацію скасовано. Натисни /start, щоб розпочати знову", reply_markup=ReplyKeyboardRemove())


# --- 2. /help посеред реєстрації: авто-категорія ---
@reg_router.message(StateFilter(Registration), Command("help"))
async def help_during_registration(message: Message, state: FSMContext):
    active_ticket = await db.get_active_ticket(message.from_user.id)
    if active_ticket:
        await message.answer("Ти вже маєш відкритий запит! 😉 Пиши прямо сюди, у чат")
        return

    current_state = await state.get_state()
    await state.update_data(category="Реєстрація", return_state=current_state)
    await state.set_state(TicketFSM.writing_first_message)
    await message.answer(
        "<b>🌟 Svitlo Support Centre 🌟</b>\n"
        "Опиши питання чи проблему. Живий куратор відповість найближчим часом!\n\n"
        "<i>Твій прогрес реєстрації нікуди не дінеться — продовжиш одразу після закриття запиту</i>",
        parse_mode="HTML",
        reply_markup=kb.get_ticket_cancel_kb()
    )

# endregion =====================================================
# region START FLOW
# ===============================================================

@reg_router.message(Command("start"), ~StateFilter(Registration))
@reg_router.message(Command("start"), StateFilter(Registration.waiting_email))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    student = student_ctx.get()
    student_stage = student['data'].get('stage') if student else None

    if student and student_stage in ['student', 'alumni']:
        # Студент вже ідентифікований (має прив'язаний telegramId)
        await message.answer(
            "Привіт! Я — твій помічник у SvitloSchool ☺️\n<b>Ти вже є в загальному чаті своєї вікової групи?</b>",
            parse_mode="HTML",
            reply_markup=kb.get_start_menu()
        )
    else:
        # Невідомий користувач (старий студент без ТГ або новий лід)
        registration_open = await db.get_registration_open()
        await message.answer(
            "👋 Привіт! Я — офіційний бот SvitloSchool.\n"
            "<b>Обери свій статус, щоб ми могли продовжити:</b>",
            parse_mode="HTML",
            reply_markup=kb.get_guest_start_menu(registration_open)
        )

@reg_router.callback_query(F.data == "auth_existing")
async def process_auth_existing(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(Registration.waiting_email)
    await state.update_data(emailFlowSource="guest_menu_auth_existing")

    await callback.message.delete()
    await ut.step_answer(callback.message, "🔐 <b>Синхронізація акаунта</b>")
    await ut.step_answer(callback.message, "Будь ласка, напиши свою <b>електронну пошту</b>, яку ти вказував при реєстрації у SvitloSchool:", reply_markup=kb.get_email_cancel_kb())

@reg_router.callback_query(F.data == "auth_new_lead")
async def process_auth_new_lead(callback: CallbackQuery, state: FSMContext):
    if not await db.get_registration_open():
        await callback.answer("⚠️ Наразі реєстрація нових студентів закрита", show_alert=True)
        await callback.message.edit_reply_markup(reply_markup=kb.get_guest_start_menu(registration_open=False))
        return

    await callback.answer()
    doc_id, is_new = await db.init_lead(callback.from_user.id, callback.from_user.username)

    if is_new:
        # Нагадування тим, хто натиснув "Хочу зареєструватись", але не завершив заявку —
        # 24г і 48г від цього моменту. Кожен таск сам перевіряє актуальність при спрацюванні
        # (send_reminder у api/task_routes.py), тож нічого скасовувати тут не треба.
        await enqueue_task("/tasks/send_reminder", {"doc_id": doc_id, "step": 1}, delay_seconds=24 * 3600)
        await enqueue_task("/tasks/send_reminder", {"doc_id": doc_id, "step": 2}, delay_seconds=48 * 3600)

    await callback.message.edit_text(
        LEAD_WELCOME_MSG,
        parse_mode="HTML",
        reply_markup=kb.get_start_registration_kb()
    )

@reg_router.callback_query(F.data == "start_onboarding_flow")
async def start_entering_data(callback: CallbackQuery, state: FSMContext):
    student = student_ctx.get()

    # 🛡 Fail-Fast Захист: перериваємо виконання, якщо ліда немає в базі
    if not student:
        await callback.answer("⚠️ Профіль не знайдено. Спробуй /start", show_alert=True)
        return

    await callback.answer()
    # Оновлюємо crm_stage, відмічаючи старт реєстрації
    await db.update_crm_stage(student['id'], "personal_data")

    # Запускаємо FSM
    await state.set_state(Registration.entering_first_name)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        "Чудово!\n<b>Почнімо з кількох запитань про тебе 📝</b>\n\n"
        "Ім'я та прізвище потрібно буде вказати англійською. Наші викладачі є носіями мови, тож їм важливо знати, як до тебе звертатися 😊\n\n"
        "Решту анкети можна заповнювати українською 🇺🇦"
    )
    await ut.step_answer(callback.message, _prompt(Registration.entering_first_name))

# endregion =====================================================
# region REG FSM FUNNEL
# ===============================================================

# ІМ'Я -> ПРІЗВИЩЕ
@reg_router.message(Registration.entering_first_name, F.text)
async def process_first_name(message: Message, state: FSMContext):
    first_name = message.text.strip().title()
    if not re.match(ENG_NAME_REGEX, first_name):
        await ut.step_answer(message, "⚠️ Будь ласка, введи своє ім'я англійською мовою (як в закордонному паспорті)")
        return
    if ut.is_gibberish_name(first_name):
        await ut.step_answer(message, "⚠️ Здається, це ім'я введено помилково. Будь ласка, введи своє справжнє ім'я англійською")
        return

    await state.update_data(firstName=first_name)
    await state.set_state(Registration.entering_last_name)
    await ut.step_answer(message, f"Thanks {first_name}!\n{_prompt(Registration.entering_last_name)}")

# ПРІЗВИЩЕ -> СТАТЬ
@reg_router.message(Registration.entering_last_name, F.text)
async def process_last_name(message: Message, state: FSMContext):
    last_name = message.text.strip().title()
    if not re.match(ENG_NAME_REGEX, last_name):
        await ut.step_answer(message, "⚠️ Будь ласка, введи своє прізвище англійською мовою (як в закордонному паспорті)")
        return
    if ut.is_gibberish_name(last_name):
        await ut.step_answer(message, "⚠️ Здається, це прізвище введено помилково. Будь ласка, введи своє справжнє прізвище англійською")
        return

    await state.update_data(lastName=last_name)
    data = await state.get_data()
    full_name = f"{data.get('firstName', '')} {last_name}"
    
    await state.set_state(Registration.entering_gender)
    await message.answer(
        f"Nice to meet you, {full_name}! ☺️\n\n"
        "<b>Зверни увагу, решту заявки слід заповнювати українською!</b> 🇺🇦"
    )
    await message.bot.send_chat_action(message.chat.id, "upload_photo")
    await asyncio.sleep(1)
    await message.answer_media_group(_replykb_hint())
    await ut.step_answer(message, _prompt(Registration.entering_gender), reply_markup=kb.get_gender_kb(), parse_mode="HTML")

# СТАТЬ -> ДАТА НАРОДЖЕННЯ
@reg_router.message(Registration.entering_gender, F.text)
async def process_gender(message: Message, state: FSMContext):
    gender = message.text.strip()
    if gender in ['Чоловіча', 'Жіноча', 'Волію не вказувати']:
        if gender == "Чоловіча": db_gender = "Male"
        elif gender == "Жіноча": db_gender = "Female"
        else: db_gender = "Unspecified"
        await state.update_data(gender=db_gender)

        await state.set_state(Registration.entering_dob)
        await ut.step_answer(message,
            _prompt(Registration.entering_dob),
            reply_markup=ReplyKeyboardRemove()
        )
    else:
        await ut.step_answer(message, "Будь ласка, скористайся варіантами внизу екрана ↘️", reply_markup=kb.get_gender_kb())

# ДАТА НАРОДЖЕННЯ -> EMAIL
@reg_router.message(Registration.entering_dob, F.text)
async def process_dob(message: Message, state: FSMContext):
    dob_str = message.text.strip()
    try:
        # Валідація дати та розрахунок вікової групи
        dob_obj = datetime.strptime(dob_str, "%d.%m.%Y")
        today = datetime.now()
        age = today.year - dob_obj.year - ((today.month, today.day) < (dob_obj.month, dob_obj.day))
        
        if not (10 <= age <= 18):
            await ut.step_answer(message, "⚠️ Твій вік виходить за рамки стандартних програм Svitlo (10-13 та 14-18). Будь ласка, перевір правильність дати (ДД.ММ.РРРР)")
            return
            
        age_group = "older" if 14 <= age <= 18 else "younger" if 10 <= age <= 13 else "error"
        
        # Встановлюємо 12:00 UTC, щоб уникнути багів зміни дня через таймзони
        dob_timestamp = dob_obj.replace(hour=12, tzinfo=timezone.utc)
        
        # Тепер в FSM лежить нативний об'єкт datetime
        await state.update_data(birthDate=dob_timestamp, ageGroup=age_group)
        await state.set_state(Registration.entering_email)
        await message.answer("Чудово! 😊\n"
                             "Тепер перейдімо до твоїх контактних даних")
        await ut.step_answer(message, _prompt(Registration.entering_email))
    except ValueError:
        await ut.step_answer(message, "⚠️ Неправильний формат дати. Використовуй формат ДД.ММ.РРРР (наприклад, 24.08.2011)")

async def _check_email_typo(message: Message, state: FSMContext, email: str, pending_key: str) -> bool:
    """Якщо домен схожий на одруку в популярному провайдері (gmail.con тощо) — просить підтвердити.
    Повертає True, якщо обробку слід зупинити (чекаємо на повторне підтвердження від юзера)."""
    data = await state.get_data()
    suggestion = ut.suggest_email_domain_fix(email)

    if suggestion and data.get(pending_key) != email:
        await state.update_data(**{pending_key: email})
        await ut.step_answer(message, 
            f"🤔 Здається, в домені пошти невеличка помилка. Може, ти мав(-ла) на увазі {suggestion}?\n\n"
            f"Будь ласка, перевір та повтори ввід пошти:"
        )
        return True

    if data.get(pending_key):
        await state.update_data(**{pending_key: None})
    return False

# EMAIL -> ТЕЛЕФОН
@reg_router.message(Registration.entering_email, F.text)
async def process_email(message: Message, state: FSMContext):
    email = message.text.lower().strip()
    if not re.match(EMAIL_REGEX, email):
        await ut.step_answer(message, "⚠️ Неправильний формат. Спробуй ще раз (приклад: <code>user@gmail.com</code>):")
        return
    if await _check_email_typo(message, state, email, "emailTypoPending"):
        return

    await state.update_data(email=email)
    await state.set_state(Registration.entering_phone)
    
    await message.answer("Дякую, тепер <b>натисни кнопку «Поділитись номером»</b> нижче, аби надіслати нам свій контакт! Це допоможе зберегти твій номер телефону в правильному форматі та залишатись на зв'язку 😌", reply_markup=kb.get_number_for_registration_kb())
    await ut.step_answer(message, "<blockquote>ℹ️ Telegram може відкрити стандартне системне вікно для верифікації — <b>це безпечна процедура авторизації, просто підтвердь дію</b></blockquote>")

# ТЕЛЕФОН -> КРАЇНА
# Прийом виключно контактних даних від кнопки
@reg_router.message(Registration.entering_phone, F.contact)
async def process_phone_contact(message: Message, state: FSMContext):
    if message.contact.user_id != message.from_user.id:
        await ut.step_answer(message, "⚠️ Будь ласка, надішли саме свій контакт за допомогою кнопки <b>«Поділитись номером»</b> внизу екрана ↘️")
        return
    
    phone = ut.normalize_phone(message.contact.phone_number)
    if not phone:
        await ut.step_answer(message, "⚠️ Не вдалося розпізнати номер. Спробуй надіслати контакт ще раз ↘️")
        return

    student = student_ctx.get()
    if not student:
        await ut.step_answer(message, "⚠️ Помилка сесії: Профіль не знайдено. Надішли /start")
        return

    if ut.is_russian_phone_number(phone):
        await db.update_crm_stage(student['id'], "blocked")
        await db.clear_user_fsm(message.from_user.id)
        await ut.step_answer(message, "⚠️ Доступ до реєстрації в Svitlo School обмежено")
        return
    
    await state.update_data(phone=phone)
    await state.set_state(Registration.entering_country)
    
    await ut.step_answer(message, _prompt(Registration.entering_country), parse_mode="HTML", reply_markup=ReplyKeyboardRemove())

# Блокування ручного введення
@reg_router.message(Registration.entering_phone, F.text)
async def process_phone_text_blocked(message: Message):
    await ut.step_answer(message, 
        "⚠️ Ручне введення вимкнено.\n\n"
        "Будь ласка, скористайся кнопкою <b>«Поділитись номером»</b> внизу екрана ↘️",
        reply_markup=kb.get_number_for_registration_kb()
    )

# КРАЇНА -> МІСТО
@reg_router.message(Registration.entering_country, F.text)
async def process_country(message: Message, state: FSMContext):
    country = message.text.strip().title()
    student = student_ctx.get()
    if not student:
        await ut.step_answer(message, "⚠️ Помилка сесії: Профіль не знайдено. Надішли /start")
        return

    if not re.match(UKR_REGEX, country):
        await ut.step_answer(message, "⚠️ Будь ласка, вкажи країну українською мовою (наприклад: Україна, Польща)")
        return

    if ut.is_russian_country_input(country):
        await db.update_crm_stage(student['id'], "blocked")
        await db.clear_user_fsm(message.from_user.id)
        await ut.step_answer(message, "⚠️ Доступ до реєстрації в Svitlo School обмежено")
        return

    await state.update_data(country=country)
    await state.set_state(Registration.entering_city)
    await ut.step_answer(message, "Вкажи назву <b>міста чи села</b>, де ти зараз мешкаєш:")

# МІСТО -> ВПО
@reg_router.message(Registration.entering_city, F.text)
async def process_city(message: Message, state: FSMContext):
    city = message.text.strip().title()
    student = student_ctx.get()
    if not student:
        await ut.step_answer(message, "⚠️ Помилка сесії: Профіль не знайдено. Надішли /start")
        return

    if not re.match(UKR_REGEX, city):
        await ut.step_answer(message, "⚠️ Будь ласка, вкажи місто чи село українською мовою")
        return

    if ut.is_russian_country_input(city):
        await db.update_crm_stage(student['id'], "blocked")
        await db.clear_user_fsm(message.from_user.id)
        await ut.step_answer(message, "⚠️ Доступ до реєстрації в Svitlo School обмежено")
        return

    await state.update_data(city=city)
    await state.set_state(Registration.entering_displaced_bool)
    await message.answer("Дякую! 50% заявки вже позаду 😉")
    await message.bot.send_chat_action(message.chat.id, "typing")
    await asyncio.sleep(1)
    await ut.step_answer(message, 
        "<b>Чи довелося тобі змінити місце проживання через війну?</b>",
        reply_markup=kb.get_boolean_kb()
    )
    await ut.step_answer(message, 
        "<blockquote>ℹ️ Ця інформація допомагає нам підтримувати студентів та адаптовувати навчальні програми</blockquote>",
        reply_markup=kb.get_boolean_kb()
    )

# ВПО -> Область (якщо Так) або Батьки (якщо Ні)
@reg_router.message(Registration.entering_displaced_bool, F.text)
async def process_displaced_status(message: Message, state: FSMContext):
    text = message.text.strip().lower()
    if text == "так":
        await state.update_data(isDisplaced=True)
        await state.set_state(Registration.entering_displaced_region)
        await ut.step_answer(message, 
            "<b>З якої області України ти переїхав(-ла)?</b>",
            reply_markup=ReplyKeyboardRemove()
        )
    elif text == "ні":
        await state.update_data(isDisplaced=False, displacedRegion="")
        await state.set_state(Registration.entering_parent_first_name)
        
        await message.answer(
            "Дякую! Далі кілька запитань про одного з твоїх батьків або опікунів. Це необхідно, аби ми могли зв’язатися з ними в разі надзивчайної ситуації",
            reply_markup=ReplyKeyboardRemove()
        )
        await ut.step_answer(message, "Вкажи <b>ім'я одного з батьків/опікунів</b>:")
    else:
        await ut.step_answer(message, "⚠️ Будь ласка, обери «Так» або «Ні»:", reply_markup=kb.get_boolean_kb())

# Область переміщених -> Батьки
@reg_router.message(Registration.entering_displaced_region, F.text)
async def process_displaced_region(message: Message, state: FSMContext):
    region = message.text.strip().title()
    if not re.match(UKR_REGEX, region):
        await ut.step_answer(message, "⚠️ Будь ласка, вкажи область українською мовою")
        return

    await state.update_data(displacedRegion=region)
    await state.set_state(Registration.entering_parent_first_name)
    
    await message.answer(
                "🫂 Дякую, твоя щирість є дуже цінною для нас!\n\n"
                "Далі кілька запитань про одного з твоїх батьків або опікунів. Це необхідно, аби ми могли зв’язатися з ними в разі надзивчайної ситуації",
                reply_markup=ReplyKeyboardRemove()
            )
    await ut.step_answer(message, "Вкажи <b>ім'я одного з батьків/опікунів</b>:")

# БАТЬКИ (Ім'я -> Прізвище -> Email -> Телефон)
@reg_router.message(Registration.entering_parent_first_name, F.text)
async def process_parent_first_name(message: Message, state: FSMContext):
    parent_first_name = message.text.strip().title()
    if not re.match(UKR_REGEX, parent_first_name):
        await ut.step_answer(message, "⚠️ Будь ласка, вкажи ім'я українською мовою")
        return

    await state.update_data(parentFirstName=parent_first_name)
    await state.set_state(Registration.entering_parent_last_name)
    await ut.step_answer(message, "Вкажи <b>прізвище одного з батьків/опікунів</b>:")

@reg_router.message(Registration.entering_parent_last_name, F.text)
async def process_parent_last_name(message: Message, state: FSMContext):
    parent_last_name = message.text.strip().title()
    if not re.match(UKR_REGEX, parent_last_name):
        await ut.step_answer(message, "⚠️ Будь ласка, вкажи прізвище українською мовою")
        return

    await state.update_data(parentLastName=parent_last_name)
    await state.set_state(Registration.entering_parent_email)
    await ut.step_answer(message, "Яка <b>електронна пошта в одного з твоїх батьків/опікунів?</b>")

@reg_router.message(Registration.entering_parent_email, F.text)
async def process_parent_email(message: Message, state: FSMContext):
    email = message.text.lower().strip()
    if not re.match(EMAIL_REGEX, email):
        await ut.step_answer(message, "⚠️ Неправильний формат. Спробуй ще раз (приклад: <code>user@gmail.com</code>):")
        return

    data = await state.get_data()
    if email == data.get('email'):
        await ut.step_answer(message, "⚠️ Це та сама пошта, що і твоя особиста. Будь ласка, вкажи пошту одного з батьків/опікунів:")
        return
    if await _check_email_typo(message, state, email, "parentEmailTypoPending"):
        return

    await state.update_data(parentEmail=email)
    await state.set_state(Registration.entering_parent_phone)
    await ut.step_answer(message, "І який <b>номер телефону в одного з твоїх батьків/опікунів?</b> Вкажи у міжнародному форматі (наприклад, +380...)")

@reg_router.message(Registration.entering_parent_phone, F.text)
async def process_parent_phone(message: Message, state: FSMContext):
    phone = ut.normalize_phone(message.text)
    if not phone:
        await ut.step_answer(message, "⚠️ Такого номера не існує. Перевір цифри й введи у міжнародному форматі (+380...):")
        return

    data = await state.get_data()
    if phone == data.get('phone'):
        await ut.step_answer(message, "⚠️ Це той самий номер, що і твій особистий. Будь ласка, вкажи номер одного з батьків/опікунів (+380...):")
        return

    await state.update_data(parentPhone=phone)
    await state.set_state(Registration.entering_lead_source)
    await message.answer("Дякую! 😊 Залишилось всього 2 запитання, і цей розділ завершено!")
    await ut.step_answer(message, "<b>Звідки ти дізнався(-лась) про Svitlo School?</b> Обери або напиши свій варіант:", 
                         reply_markup=kb.get_lead_source_kb())

# ДЖЕРЕЛО ТРАФІКУ
@reg_router.message(Registration.entering_lead_source, F.text)
async def process_lead_source(message: Message, state: FSMContext):
    lead_source = message.text.strip()
    if lead_source in ("Інше", "Організація"):
        await state.update_data(leadSourceType=lead_source)
        await state.set_state(Registration.entering_lead_source_details)
        if lead_source == "Інше":
            await ut.step_answer(message, "Будь ласка, коротко уточни звідки чи від кого:", reply_markup=ReplyKeyboardRemove())
        else:
            await ut.step_answer(message, "Будь ласка, уточни назву організації:", reply_markup=ReplyKeyboardRemove())
        return

    await state.update_data(leadSource=lead_source)
    await state.set_state(Registration.entering_health_bool)
    await ut.step_answer(message, "І наостанок: чи є у тебе особливі потреби, пов’язані зі станом здоров’я або інвалідністю, про які нам варто знати для твоєї найкращої підтримки в Svitlo School? Наприклад, медичні застереження, потреби в адаптації матеріалів чи забезпеченні доступності", reply_markup=kb.get_boolean_kb())

# ДЖЕРЕЛО ТРАФІКУ (уточнення для "Інше" / "Організація")
@reg_router.message(Registration.entering_lead_source_details, F.text)
async def process_lead_source_details(message: Message, state: FSMContext):
    data = await state.get_data()
    lead_source_type = data.get("leadSourceType", "Інше")
    details = message.text.strip()

    await state.update_data(leadSource=f"{lead_source_type}: {details}")
    await state.set_state(Registration.entering_health_bool)
    await ut.step_answer(message, "І наостанок: чи є у тебе особливі потреби, пов’язані зі станом здоров’я або інвалідністю, про які нам варто знати для твоєї найкращої підтримки в Svitlo School? Наприклад, медичні застереження, потреби в адаптації матеріалів чи забезпеченні доступності", reply_markup=kb.get_boolean_kb())

# ЗДОРОВ'Я ТА ІНКЛЮЗІЯ
@reg_router.message(Registration.entering_health_bool, F.text)
async def process_health_bool(message: Message, state: FSMContext):
    if message.text.strip().lower() == "так":
        await state.update_data(hasHealthIssues=True)
        await state.set_state(Registration.entering_health_details)
        await ut.step_answer(message, "Будь ласка, опиши їх коротко (це важливо, аби могли забезпечити інклюзивне середовище):", reply_markup=ReplyKeyboardRemove())
    elif message.text.strip().lower() == "ні":
        await state.update_data(hasHealthIssues=False, healthIssuesDetails="")
        await _show_data_confirmation(message, state)
    else:
        await ut.step_answer(message, "⚠️ Будь ласка, обери «Так» або «Ні»:", reply_markup=kb.get_boolean_kb())

@reg_router.message(Registration.entering_health_details, F.text)
async def process_health_details(message: Message, state: FSMContext):
    await state.update_data(healthIssuesDetails=message.text.strip())
    await _show_data_confirmation(message, state)


# ==========================================
# Логіка перевірки заявки та редагування
# ==========================================


def _build_confirmation_summary(data: dict) -> str:
    health_txt = f"Так ({ut.esc_html(data.get('healthIssuesDetails'))})" if data.get('hasHealthIssues') else "Ні"
    disp_txt = f"Так ({data.get('displacedRegion')})" if data.get('isDisplaced') else "Ні"
    dob_obj = data.get('birthDate')
    dob_str = dob_obj.strftime("%d.%m.%Y") if hasattr(dob_obj, "strftime") else "Не вказано"

    return (
        "<b>Перевір свої дані перед збереженням:</b>\n\n"
        f"👤 <b>Ім'я:</b> {data.get('firstName')} {data.get('lastName')}\n"
        f"📅 <b>Дата народження:</b> {dob_str}\n"
        f"📧 <b>Email:</b> {data.get('email')}\n"
        f"📱 <b>Телефон:</b> {data.get('phone')}\n"
        f"📍 <b>Проживання:</b> {data.get('city')}, {data.get('country')}\n"
        f"🕊 <b>ВПО:</b> {disp_txt}\n\n"
        f"👨‍👩‍👧 <b>Відповідальна особа:</b>\n{data.get('parentFirstName')} {data.get('parentLastName')}\n{data.get('parentEmail')}\n{data.get('parentPhone')}\n"
        f"🏥 <b>Особливі потреби:</b> {health_txt}\n\n"
        "Усе правильно?"
    )

async def _show_data_confirmation(message: Message, state: FSMContext):
    data = await state.get_data()
    await state.set_state(Registration.confirming_data)
    await message.answer(_build_confirmation_summary(data), reply_markup=kb.get_data_confirmation_kb())

@reg_router.callback_query(Registration.confirming_data, F.data == "confirm_data_success")
async def confirm_data_success(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    await _finalize_personal_data(callback.message, state)

@reg_router.callback_query(Registration.confirming_data, F.data == "confirm_data_edit")
async def confirm_data_edit(callback: CallbackQuery):
    await callback.answer()
    old_html = callback.message.html_text
    new_html = old_html.replace("Усе правильно?", "<b>Що саме потрібно змінити?</b>")
    
    await callback.message.edit_text(text=new_html, reply_markup=kb.get_edit_fields_kb())

@reg_router.callback_query(Registration.confirming_data, F.data.startswith("edit_field:"))
async def select_field_to_edit(callback: CallbackQuery, state: FSMContext):
    field = callback.data.split(":")[1]
    await callback.answer()
    
    if field == "cancel":
        await callback.message.delete()
        return await _show_data_confirmation(callback.message, state)

    await state.update_data(editingField=field)
    await state.set_state(Registration.editing_field)

    await callback.message.delete()
    await ut.step_answer(callback.message, EDIT_FIELD_PROMPTS[field])

@reg_router.message(Registration.editing_field)
async def process_field_edit(message: Message, state: FSMContext):
    data = await state.get_data()
    field = data.get("editingField")

    if field == "firstName":
        val = message.text.strip().title()
        if not re.match(ENG_NAME_REGEX, val):
            return await ut.step_answer(message, "⚠️ Будь ласка, введи своє ім'я англійською мовою (як в закордонному паспорті)")
        if ut.is_gibberish_name(val):
            return await ut.step_answer(message, "⚠️ Здається, це ім'я введено помилково. Будь ласка, введи своє справжнє ім'я англійською")
        await state.update_data(firstName=val)

    elif field == "lastName":
        val = message.text.strip().title()
        if not re.match(ENG_NAME_REGEX, val):
            return await ut.step_answer(message, "⚠️ Будь ласка, введи своє прізвище англійською мовою (як в закордонному паспорті)")
        if ut.is_gibberish_name(val):
            return await ut.step_answer(message, "⚠️ Здається, це прізвище введено помилково. Будь ласка, введи своє справжнє прізвище англійською")
        await state.update_data(lastName=val)

    elif field == "birthDate":
        try:
            dob_obj = datetime.strptime(message.text.strip(), "%d.%m.%Y")
            today = datetime.now()
            age = today.year - dob_obj.year - ((today.month, today.day) < (dob_obj.month, dob_obj.day))
            if not (10 <= age <= 18):
                return await ut.step_answer(message, "⚠️ Твій вік виходить за рамки стандартних програм Svitlo (10-13 та 14-18). Будь ласка, перевір правильність дати (ДД.ММ.РРРР)")
            age_group = "older" if 14 <= age <= 18 else "younger"
            dob_timestamp = dob_obj.replace(hour=12, tzinfo=timezone.utc)
            await state.update_data(birthDate=dob_timestamp, ageGroup=age_group)
        except ValueError:
            return await ut.step_answer(message, "⚠️ Неправильний формат дати. Використовуй формат ДД.ММ.РРРР (наприклад, 24.08.2011)")

    elif field == "email":
        val = message.text.lower().strip()
        if not re.match(EMAIL_REGEX, val):
            return await ut.step_answer(message, "⚠️ Неправильний формат. Спробуй ще раз (приклад: <code>user@gmail.com</code>):")
        if await _check_email_typo(message, state, val, "editEmailTypoPending"):
            return
        await state.update_data(email=val)

    elif field == "country":
        val = message.text.strip().title()
        if not re.match(UKR_REGEX, val):
            return await ut.step_answer(message, "⚠️ Будь ласка, вкажи країну українською мовою (наприклад: Україна, Польща)")
        if ut.is_russian_country_input(val):
            return await ut.step_answer(message, "⚠️ Доступ до реєстрації в Svitlo School обмежено")
        await state.update_data(country=val)

    elif field == "city":
        val = message.text.strip().title()
        if not re.match(UKR_REGEX, val):
            return await ut.step_answer(message, "⚠️ Будь ласка, вкажи місто чи село українською мовою")
        if ut.is_russian_country_input(val):
            return await ut.step_answer(message, "⚠️ Доступ до реєстрації в Svitlo School обмежено")
        await state.update_data(city=val)

    # Очищуємо поле та повертаємо користувача до підтвердження
    await state.update_data(editingField=None)
    await _show_data_confirmation(message, state)

# endregion =====================================================
# region INTERLUDE #1
# ===============================================================

async def _finalize_personal_data(message: Message, state: FSMContext):
    """Допоміжна функція: зберігає зібраний FSM-словник у Firestore та переводить на етап правил"""
    data = await state.get_data()
    student = student_ctx.get()

    if not student:
        await ut.step_answer(message, "⚠️ Помилка сесії: Профіль не знайдено. Надішли /start")
        return
        
    doc_id = student['id']
    await db.save_lead_profile(doc_id, data, "rules_matching")

    # Антидубль-перевірка: інша анкета з тим самим email/телефоном -> позначаємо для куратора, не блокуємо
    dup = await db.find_duplicate_applicant(doc_id, data.get('email', ''), data.get('phone', ''))
    if dup:
        await firestore_client.collection('Svitlo').document(doc_id).update({"possibleDuplicateId": dup['id']})

    await state.set_state(Registration.passing_rules)

    await message.edit_text(
        LEAD_INTERLUDE_1_MSG,
        reply_markup=kb.get_rules_start_kb()
    )

# endregion =====================================================
# region RULES, QUIZ & ID
# ===============================================================

@reg_router.callback_query(Registration.passing_rules, F.data == "rules_start")
async def process_rules(callback: CallbackQuery, state: FSMContext):
    await state.update_data(quizStep=0)
    await callback.answer()
    await callback.message.edit_text(
            RULES_MSG,
            reply_markup=kb.get_quiz_start_kb(),
            disable_web_page_preview=True
        )
    
@reg_router.callback_query(Registration.passing_rules, (F.data.startswith("ans_")) | (F.data == "quiz_start"))
async def process_quiz(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    step = data.get("quizStep", 0)
    
    if callback.data.startswith("ans_"):
        ans_idx = int(callback.data.split("_")[1])
        
        # 1. Логіка при неправильній відповіді
        if ans_idx != QUIZ_DATA[step - 1]["correct"]:
            student = student_ctx.get()
            if student:
                await db.increment_rules_mistake(student['id'])

            await callback.answer(
                "❌ Неправильно! Повертаємось до правил. Уважно перечитай їх та спробуй пройти квіз ще раз",
                show_alert=True
            )
            # Скидаємо прогрес
            await state.update_data(quizStep=0)
            # Повертаємо повідомлення з правилами та кнопкою "Take the quiz"
            await callback.message.edit_text(
                RULES_MSG,
                reply_markup=kb.get_quiz_start_kb(),
                disable_web_page_preview=True
            )
            return 
            
    # 2. Логіка при правильній відповіді або натисканні "quiz_start"
    if step < len(QUIZ_DATA):
        question = QUIZ_DATA[step]
        text_to_send = f"<b>📚 Check Your Rules Knowledge 📚</b>\n\n{question['q']}"

        await callback.answer()
        await callback.message.edit_text(
            text_to_send,
            reply_markup=kb.get_quiz_kb(question["options"])
        )
        await state.update_data(quizStep=step + 1)
        
    # 3. Логіка успішного завершення
    else:
        await callback.answer()

        data = await state.get_data()
        first_name = data.get('firstName', '')

        student = student_ctx.get()
        if student:
            await db.update_crm_stage(student['id'], "uploading_docs")

        interlude_msg = await callback.message.edit_text(LEAD_INTERLUDE_2_MSG.format(name=first_name))
        scanner_msg = await callback.message.answer(SCANNER_MSG, reply_markup=kb.get_scanner_webapp_kb())
        # Зберігаємо ID цих двох повідомлень, щоб прибрати їх з чату після успішного сканування
        await state.update_data(scanner_msg_ids=[interlude_msg.message_id, scanner_msg.message_id])
        await state.set_state(Registration.uploading_docs)

@reg_router.message(Command("testcam"), IsTesterFilter())
async def cmd_test_idcheck(message: Message, state: FSMContext):
    await message.answer(SCANNER_MSG, reply_markup=kb.get_scanner_webapp_kb())

# Далі дія переходить у api/webapp_routes.py, де, в разі успіху, 
# лід переводиться на етап Registration.admin_review, а адміністратор отримує його профіль на розгляд

# endregion =====================================================
# region ADMIN REVIEW
# ===============================================================

@reg_router.callback_query(F.data == "hidden_profile_alert")
async def alert_hidden_profile(callback: CallbackQuery):
    """Показує повідомлення куратору, якщо у ліда немає юзернейму"""
    await callback.answer(
        "⚠️ У студента прихований профіль без юзернейму.\n"
        "Скористайся його номером телефону, щоб зв'язатися", 
        show_alert=True
    )

@reg_router.callback_query(F.data.startswith("lead_details_"))
async def admin_show_lead_details(callback: CallbackQuery):
    doc_id = callback.data.split("_")[2]
    
    doc = await firestore_client.collection('Svitlo').document(doc_id).get()
    if not doc.exists:
        await callback.answer("Анкету не знайдено", show_alert=True)
        return
        
    data = doc.to_dict()
    health_text = f"Так ({ut.esc_html(data.get('healthIssuesDetails'))})" if data.get('hasHealthIssues') else "Ні"

    tg_username = data.get('telegramUsername', '').replace('@', '')
    phone = data.get('phone', 'Не вказано')
    display_username = f"@{tg_username}" if tg_username else "Без юзернейму"

    # Форматування дати народження для читабельності
    dob = data.get('birthDate')
    dob_str = dob.strftime("%d.%m.%Y") if hasattr(dob, 'strftime') else str(dob)

    displaced_info = f"Так ({data.get('displacedRegion')})" if data.get('isDisplaced') else "Ні"

    dup_id = data.get('possibleDuplicateId')
    dup_warning = f"⚠️ <b>Можливий дублікат заявки:</b> <code>{dup_id}</code>\n\n" if dup_id else ""

    ai_info_block = ut.format_ai_info_block(data.get('aiInfo'))

    detailed_text = (
        f"{dup_warning}"
        f"<b>📋 Повна анкета: {data.get('firstName')} {data.get('lastName')}</b>\n\n"
        f"<b>Дата народження:</b> {dob_str} ({data.get('ageGroup')})\n"
        f"<b>Email:</b> {data.get('email')}\n"
        f"<b>Контакти:</b>\n{phone}\n{display_username}\n"
        f"<b>Стать:</b> {data.get('gender')}\n"
        f"<b>Локація:</b> {data.get('city')}, {data.get('country')}\n"
        f"<b>Джерело ліда:</b> {ut.esc_html(data.get('leadSource'))}\n\n"
        f"<b>ВПО/біженець:</b> {displaced_info}\n"
        f"<b>Проблеми зі здоров'ям:</b> {health_text}\n\n"
        f"<b>Відповідальна особа:</b>\n{data.get('parentFirstName')} {data.get('parentLastName')}\n"
        f"{data.get('parentPhone')}\n{data.get('parentEmail')}\n\n"
        f"{ai_info_block}\n"
        f"<i>⚠️ Звір з даними анкети вище</i>"
    )

    keyboard = kb.get_admin_action_kb(doc_id, tg_username, include_details_btn=False)

    await callback.answer()
    await callback.message.edit_text(detailed_text, reply_markup=keyboard)

@reg_router.callback_query(F.data.startswith("lead_confirmblock_"))
async def admin_confirm_block_lead(callback: CallbackQuery):
    doc_id = callback.data.split("_")[2]
    await callback.answer()
    await callback.message.edit_reply_markup(
        reply_markup=kb.get_admin_confirm_block_kb(doc_id)
    )

@reg_router.callback_query(F.data.startswith("lead_block_"))
async def admin_block_lead(callback: CallbackQuery):
    await callback.answer("Заявку заблоковано")
    doc_id = callback.data.split("_")[2]
    
    # 1. Отримуємо документ для витягування telegramId
    doc_ref = firestore_client.collection('Svitlo').document(doc_id)
    doc = await doc_ref.get()
    
    if not doc.exists:
        await callback.message.edit_text(f"{callback.message.html_text}\n\n❌ <b>Помилка: Анкету не знайдено</b>")
        return

    data = doc.to_dict()
    user_id = data.get('telegramId')

    # 2. Переводимо stage в blocked у Flat Schema
    await db.update_crm_stage(doc_id, "blocked")
    await db.clear_user_fsm(user_id)

    # 3. Оновлюємо інтерфейс куратора
    reviewer_name = callback.from_user.full_name
    await callback.message.edit_text(
        f"<b>⛔️ ЗАЯКУ ВІДХИЛЕНО</b>\n"
        f"Куратор: {reviewer_name}\n\n"
        f"{callback.message.html_text}",
        reply_markup=None
    )

    # 4. Сповіщаємо спамера (опціонально)
    if user_id:
        try:
            await callback.bot.send_message(
                chat_id=user_id,
                text="❌ <b>Твою заявку було відхилено адміністратором.</b> Доступ до системи обмежено",
                parse_mode="HTML"
            )
        except Exception:
            pass # Якщо юзер уже заблокував бота

@reg_router.callback_query(F.data.startswith("lead_approve_"))
async def admin_approve_lead(callback: CallbackQuery):
    await callback.answer()
    doc_id = callback.data.split("_")[2]
    
    # 1. Оновлюємо статус в БД на 'student'
    await firestore_client.collection('Svitlo').document(doc_id).update({
        "roles": firestore.ArrayUnion(["student"]) # Додаємо роль, не затираючи вже наявні
    })
    await db.update_crm_stage(doc_id, "student")


    # 2. Оновлюємо інтерфейс куратора
    reviewer_name = callback.from_user.full_name
    await callback.message.edit_text(
        f"{callback.message.html_text}\n\n"
        f"✅ <b>ЗАРАХОВАНО!</b> (Куратор: {reviewer_name})",
        parse_mode="HTML",
        reply_markup=None # Видаляємо кнопки
    )

    
    # 3. Асинхронно синхронізуємо студента з SchoolToday (через Cloud Tasks, щоб не блокувати вебхук)
    # Окрема черга: зарахування йдуть по одному, бо ШС не захищений від гонки
    await enqueue_task("/tasks/schooltoday_enroll", {"doc_id": doc_id},
                       queue=SCHOOLTODAY_QUEUE)

    # 4. Надсилаємо студенту привітання та Lock Screen меню
    doc = await firestore_client.collection('Svitlo').document(doc_id).get()
    data = doc.to_dict()

    user_id = data.get('telegramId')
    # Видаляємо технічний смітник з FSM_Sessions (фінальне очищення)
    await db.clear_user_fsm(user_id)
    
    first_name = data.get('firstName', 'Student')
    gender = data.get('gender', '')
    if gender == "Male": dp_gender = "студент"
    elif gender == "Female": dp_gender = "студентка"
    else: dp_gender = "студент(-ка)"

    formatted_text = APPLICATION_CONFIRMED_MSG.format(
        name=first_name,
        student=dp_gender,
        term_start_date="Понеділок, 14 вересня 2026 року",
        schooltoday_link="https://school-today.com/Profile"
    )

    await callback.bot.send_message(
        chat_id=user_id,
        text=formatted_text,
        parse_mode="HTML",
        reply_markup=kb.get_start_menu() # Кнопка "Отримати доступ"
    )

# endregion =====================================================
# region FALLBACKs
# ===============================================================

@reg_router.message(Registration.uploading_docs)
async def fallback_waiting_scan(message: Message):
    """Перехоплювач: спрацьовує, якщо замість WebApp юзер відправляє повідомлення або фото. Захищає Zero-Storage логіку."""
    await message.answer(
        "🔒 Будь ласка, скористайся кнопкою <b>«Сканувати документ»</b> для безпечної та захищеної верифікації.\n\n"
        "⚠️ Ми піклуємось про твою безпеку, тому наполегливо <b>не рекомендуємо надсилати фотографії документів в чат</b> та не приймаємо їх в такому форматі",
        reply_markup=kb.get_scanner_webapp_kb()
    )

@reg_router.message(Registration.admin_review)
async def process_admin_review_wait(message: Message):
    await message.answer("⏳ Твоя заявка зараз перевіряється куратором. Зачекай результату")

# --- 1. Ловитель невідповідного контенту/типу даних ---
@reg_router.message(StateFilter(Registration), ~StateFilter(Registration.waiting_email))
async def process_invalid_registration_input(message: Message, state: FSMContext):
    current_state = await state.get_state()

    # Окремий випливаючий підказчик залежно від стану
    if current_state == Registration.entering_phone.state:
        await ut.step_answer(message, 
            "Будь ласка, скористайся кнопкою <b>«Поділитись номером»</b> внизу екрана ↘️",
            reply_markup=kb.get_number_for_registration_kb()
        )
    elif current_state in [Registration.entering_displaced_bool.state, Registration.entering_health_bool.state]:
        await ut.step_answer(message, 
            "⚠️ Будь ласка, обери «Так» або «Ні»:",
            reply_markup=kb.get_boolean_kb()
        )
    elif current_state == Registration.uploading_docs.state:
        await ut.step_answer(message, 
            "Для верифікації документа скористайся кнопкою відкриття сканера нижче",
            reply_markup=kb.get_scanner_webapp_kb()
        )
    else:
        await ut.step_answer(message, 
            "Очікується текстова відповідь.\nБудь ласка, введи потрібні дані текстом або скористайся кнопками меню"
        )


# --- 2. Інтерцептор застарілих колбеків ---
@reg_router.callback_query(StateFilter(Registration), ~StateFilter(Registration.waiting_email))
async def process_stale_callbacks(callback: CallbackQuery, state: FSMContext):
    await callback.answer(
        "Ця кнопка застаріла або неактивна на даному етапі реєстрації. Продовжуй ввід у чаті або скористайся /help",
        show_alert=True
    )

# endregion =====================================================
# region RESUME PROMPT
# ===============================================================

def _render_passing_rules_prompt(data: dict) -> tuple[str, object]:
    step = data.get("quizStep", 0)
    if not step:
        return RULES_MSG, kb.get_quiz_start_kb()
    question = QUIZ_DATA[step - 1]
    text = f"<b>📚 Check Your Rules Knowledge 📚</b>\n\n{question['q']}"
    return text, kb.get_quiz_kb(question["options"])

async def render_registration_prompt(bot, user_id: int, state_str: str, data: dict) -> None:
    """Повторно надсилає точний текст (і клавіатуру) останнього питання анкети за станом"""
    if state_str == Registration.entering_lead_source_details.state:
        lead_type = data.get("leadSourceType", "Інше")
        text = LEAD_SOURCE_DETAILS_PROMPTS.get(lead_type, LEAD_SOURCE_DETAILS_PROMPTS["Інше"])
        await bot.send_message(chat_id=user_id, text=text, parse_mode="HTML")
        return

    if state_str == Registration.editing_field.state:
        text = EDIT_FIELD_PROMPTS.get(data.get("editingField"), "Продовж введення даних:")
        await bot.send_message(chat_id=user_id, text=text, parse_mode="HTML")
        return

    if state_str == Registration.confirming_data.state:
        await bot.send_message(
            chat_id=user_id,
            text=_build_confirmation_summary(data),
            parse_mode="HTML",
            reply_markup=kb.get_data_confirmation_kb(),
        )
        return

    if state_str == Registration.passing_rules.state:
        text, markup = _render_passing_rules_prompt(data)
        await bot.send_message(
            chat_id=user_id, text=text, parse_mode="HTML", reply_markup=markup, disable_web_page_preview=True,
        )
        return

    prompt = REGISTRATION_PROMPTS.get(state_str)
    if not prompt:
        return
    text, kb_getter = prompt
    await bot.send_message(
        chat_id=user_id, text=text, parse_mode="HTML", reply_markup=kb_getter() if kb_getter else None,
    )

# endregion =====================================================
# region
# ===============================================================
