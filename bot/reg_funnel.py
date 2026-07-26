# bot/reg_funnel.py
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
import re
from datetime import datetime
from zoneinfo import ZoneInfo
import logging

from core import database as db
from bot import keyboards as kb
from bot.states import Registration
from core.constants import QUIZ_DATA
from core.context import student_ctx
from core.config import DEV_IDS, PHONE_REGEX, EMAIL_REGEX

reg_router = Router()
reg_router.message.filter(F.from_user.id.in_(DEV_IDS), F.chat.type == "private")
reg_router.callback_query.filter(F.from_user.id.in_(DEV_IDS), F.message.chat.type == "private")

# region temporary test fns
# --- ОНОВЛЕНИЙ cmd_start ---
@reg_router.message(Command("start"), F.chat.type == "private")
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await kb.drop_reply_keyboard(message)
    student = student_ctx.get()
    student_stage = student['data'].get('crm_stage') if student else None

    if student and student_stage in ['student', 'alumni']:
        # Студент вже ідентифікований (має прив'язаний telegramId)
        await message.answer(
            "Привіт! Я — твій помічник у SvitloSchool ☺️\n<b>Ти вже є в загальному чаті своєї вікової групи?</b>",
            parse_mode="HTML",
            reply_markup=kb.get_start_menu()
        )
    else: 
        # Невідомий користувач (старий студент без ТГ або новий лід)
        await message.answer(
            "👋 Привіт! Я — офіційний бот SvitloSchool.\n"
            "<b>Обери свій статус, щоб ми могли продовжити:</b>",
            parse_mode="HTML",
            reply_markup=kb.get_guest_start_menu()
        )

# --- РОЗГАЛУЖЕННЯ ДЛЯ СТАРИХ СТУДЕНТІВ ---
@reg_router.callback_query(F.data == "auth_existing")
async def process_auth_existing(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(Registration.waiting_email)
    await callback.message.edit_text("🔐 <b>Синхронізація акаунта</b>")
    await callback.message.answer("Будь ласка, напиши свою <b>електронну пошту</b>, яку ти вказував при реєстрації у SvitloSchool:")
#endregion -----------------------------------------------------

# ===============================================================
# region NEW LEADS
# ===============================================================

@reg_router.callback_query(F.data == "auth_new_lead")
async def process_auth_new_lead(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    
    # Ініціалізуємо ліда в БД з усіма 25 колонками
    await db.init_lead(callback.from_user.id, callback.from_user.username)
    
    welcome_text = (
        "Раді тебе бачити!\n"
        "⏱️ Подача заявки до Svitlo School займає близько 17 хвилин.\n\n"
        "<b>Перш ніж почати, переконайся, що маєш:</b>\n"
        "✅ Контактні дані одного з твоїх батьків/опікунів\n"
        "✅ Твоя ID карта, закордонний паспорт або свідоцтво про народження\n\n"
        "<b>Тобі слід буде пройти три простих етапи:</b>\n"
        "1️⃣ Особиста інформація (~10 хвилин)\n"
        "2️⃣ Правила школи (~5 хвилин)\n"
        "3️⃣ Фото твого документу (~2 хвилини)\n\n"
        "<b>Коли будеш готовий, тисни нижче</b>"
    )
    
    await callback.message.edit_text(
        welcome_text, 
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
        "Чудово!\nПочнімо з кількох запитань про тебе 📝\n\n"
        "Єдине, що потрібно буде вказати англійською — це твоє ім'я. Наші викладачі є носіями мови, тож їм важливо знати, як до тебе звертатися 😊\n\n"
        "Решту анкети можна заповнювати українською"
    )
    await callback.message.answer("Будь ласка, введи своє <b>ім'я</b> (англійською):")

# endregion =====================================================
# region REG FSM FUNNEL
# ===============================================================

# ІМ'Я -> ПРІЗВИЩЕ
@reg_router.message(Registration.entering_first_name, F.text)
async def process_first_name(message: Message, state: FSMContext):
    first_name = message.text.strip().title()
    await state.update_data(first_name=first_name)
    await state.set_state(Registration.entering_last_name)
    await message.answer(f"Дякую, {first_name}!\n"
                        "Яке твоє <b>прізвище</b> (англійською)?")

# ПРІЗВИЩЕ -> СТАТЬ
@reg_router.message(Registration.entering_last_name, F.text)
async def process_last_name(message: Message, state: FSMContext):
    last_name = message.text.strip().title()
    await state.update_data(last_name=last_name)
    
    data = await state.get_data()
    full_name = f"{data.get('first_name', '')} {last_name}"
    
    await state.set_state(Registration.entering_gender)
    await message.answer(
        f"Nice to meet you, {full_name}! ☺️\n\n"
        "<b>Зверни увагу, решту заявки слід заповнювати українською!</b> 🇺🇦"
    )
    await message.answer("Обери свою <b>стать</b>:", reply_markup=kb.get_gender_kb(), parse_mode="HTML")

# СТАТЬ -> ДАТА НАРОДЖЕННЯ
@reg_router.message(Registration.entering_gender, F.text)
async def process_gender(message: Message, state: FSMContext):
    gender = message.text.strip()
    if gender in ['Чоловіча', 'Жіноча', 'Волію не відповідати']:
        await state.update_data(gender=gender)
        await state.set_state(Registration.entering_dob)
        await message.answer(
            "Введи свою <b>дату народження</b> у форматі ДД.ММ.РРРР (наприклад: 10.01.2015):",
            reply_markup=ReplyKeyboardRemove()
        )
    else:
        await message.answer("Будь ласка, скористайся варіантами внизу екрана ↘️", reply_markup=kb.get_gender_kb())

# ДАТА НАРОДЖЕННЯ -> EMAIL
@reg_router.message(Registration.entering_dob, F.text)
async def process_dob(message: Message, state: FSMContext):
    dob_str = message.text.strip()
    try:
        # Валідація дати та розрахунок вікової групи
        dob_obj = datetime.strptime(dob_str, "%d.%m.%Y")
        age = (datetime.now() - dob_obj).days // 365
        
        if not (10 <= age <= 18):
            await message.answer("⚠️ Твій вік виходить за рамки стандартних програм Svitlo (10-13 та 14-18). Будь ласка, перевір правильність дати (ДД.ММ.РРРР)")
            return
            
        age_group = "older" if 14 <= age <= 18 else "younger" if 10 <= age <= 13 else "error"
        
        # Конвертація в timezone-aware datetime одразу тут
        dob_timestamp = dob_obj.replace(tzinfo=ZoneInfo("Europe/Kyiv"))
        
        # Тепер в FSM лежить нативний об'єкт datetime
        await state.update_data(dateOfBirth=dob_timestamp, ageGroup=age_group)
        await state.set_state(Registration.entering_email)
        await message.answer("Чудово! 😊\n"
                             "Тепер перейдімо до твоїх контактних даних")
        await message.answer("Яка твоя <b>електронна пошта</b> (та, якою найчастіше користуєшся)?")
    except ValueError:
        await message.answer("⚠️ Неправильний формат дати. Використовуй формат ДД.ММ.РРРР (наприклад, 24.08.2008)")

# EMAIL -> ТЕЛЕФОН
@reg_router.message(Registration.entering_email, F.text)
async def process_email(message: Message, state: FSMContext):
    email = message.text.lower().strip()
    if not re.match(EMAIL_REGEX, email):
        await message.answer("⚠️ Неправильний формат. Спробуй ще раз (приклад: <code>user@gmail.com</code>):")
        return

    await state.update_data(email=email)
    await state.set_state(Registration.entering_phone)

    await message.answer("Який твій <b>номер телефону</b>?")
    # Повідомлення 2: Інструкція + HTML Blockquote
    phone_instructions = (
        "Тобі варто лиш <b>натиснути кнопку \n«Поділитись номером»</b> нижче — Telegram зробить усе за тебе! "
        "Це допоможе нам зберегти твій телефон у правильному форматі та залишатись на зв'язку 😌\n\n"
        "<blockquote>ℹ️ Telegram може відкрити стандартне системне вікно для верифікації — "
        "<b>це безпечна процедура авторизації, просто підтвердь дію</b></blockquote>"
    )
    await message.answer(phone_instructions, reply_markup=kb.get_number_for_registration_kb())

# ТЕЛЕФОН -> КРАЇНА
# Прийом виключно контактних даних від кнопки
@reg_router.message(Registration.entering_phone, F.contact)
async def process_phone_contact(message: Message, state: FSMContext):
    phone = message.contact.phone_number
    phone = '+' + phone if not phone.startswith('+') else phone

    await state.update_data(phone=phone)
    await state.set_state(Registration.entering_country)
    
    await message.answer("Дякую! До речі, 50% заявки вже позаду 😉", reply_markup=ReplyKeyboardRemove())
    await message.answer("<b>У якій країні</b> ти зараз проживаєш?", parse_mode="HTML")

# Блокування ручного введення
@reg_router.message(Registration.entering_phone, F.text)
async def process_phone_text_blocked(message: Message):
    await message.answer(
        "⚠️ Ручне введення вимкнено.\n\n"
        "Будь ласка, скористайся кнопкою <b>«Поділитись номером»</b> внизу екрана ↘️",
        reply_markup=kb.get_number_for_registration_kb()
    )

# КРАЇНА -> МІСТО
@reg_router.message(Registration.entering_country, F.text)
async def process_country(message: Message, state: FSMContext):
    await state.update_data(country=message.text.strip().title())
    await state.set_state(Registration.entering_city)
    await message.answer("Вкажи назву <b>міста чи села</b>, де ти зараз мешкаєш:")

# МІСТО -> ВПО
@reg_router.message(Registration.entering_city, F.text)
async def process_city(message: Message, state: FSMContext):
    await state.update_data(city=message.text.strip().title())
    await state.set_state(Registration.entering_displaced_bool)
    await message.answer(
        "<b>Чи довелося тобі змінити місце проживання через війну? 🕊</b>\n"
        "<blockquote>ℹ️ Ця інформація допомагає нам підтримувати студентів та адаптовувати навчальні програми</blockquote>",
        reply_markup=kb.get_boolean_kb()
    )

# ВПО -> Область (якщо Так) або Батьки (якщо Ні)
@reg_router.message(Registration.entering_displaced_bool, F.text)
async def process_displaced_status(message: Message, state: FSMContext):
    text = message.text.strip().lower()
    if text == "так":
        await state.update_data(is_displaced=True)
        await state.set_state(Registration.entering_displaced_region)
        await message.answer(
            "<b>З якої області України ти переїхав(-ла)?</b>",
            reply_markup=ReplyKeyboardRemove()
        )
    elif text == "ні":
        await state.update_data(is_displaced=False, displaced_region="")
        await state.set_state(Registration.entering_parent_first_name)
        
        await message.answer(
            "Дякую! Далі кілька запитань про одного з твоїх батьків або опікунів. Це необхідно, аби ми могли зв’язатися з ними в разі надзивчайної ситуації",
            reply_markup=ReplyKeyboardRemove()
        )
        await message.answer("<b>Вкажи ім'я одного з батьків/опікунів</b>:")
    else:
        await message.answer("⚠️ Будь ласка, обери «Так» або «Ні»:", reply_markup=kb.get_boolean_kb())

# Область переміщених -> Батьки
@reg_router.message(Registration.entering_displaced_region, F.text)
async def process_displaced_region(message: Message, state: FSMContext):
    await state.update_data(displaced_region=message.text.strip().title())
    await state.set_state(Registration.entering_parent_first_name)
    
    await message.answer(
                "🫂 Дякую, твоя щирість є дуже цінною для нас!\n\n"
                "Далі кілька запитань про одного з твоїх батьків або опікунів. Це необхідно, аби ми могли зв’язатися з ними в разі надзивчайної ситуації",
                reply_markup=ReplyKeyboardRemove()
            )
    await message.answer("<b>Вкажи ім'я одного з батьків/опікунів</b>:")

# БАТЬКИ (Ім'я -> Прізвище -> Email -> Телефон)
@reg_router.message(Registration.entering_parent_first_name, F.text)
async def process_parent_first_name(message: Message, state: FSMContext):
    await state.update_data(parent_first_name=message.text.strip().title())
    await state.set_state(Registration.entering_parent_last_name)
    await message.answer("<b>Вкажи прізвище одного з батьків/опікунів</b>:")

@reg_router.message(Registration.entering_parent_last_name, F.text)
async def process_parent_last_name(message: Message, state: FSMContext):
    await state.update_data(parent_last_name=message.text.strip().title())
    await state.set_state(Registration.entering_parent_email)
    await message.answer("<b>Яка електронна пошта в одного з твоїх батьків/опікунів?</b>")

@reg_router.message(Registration.entering_parent_email, F.text)
async def process_parent_email(message: Message, state: FSMContext):
    email = message.text.lower().strip()
    if not re.match(EMAIL_REGEX, email):
        await message.answer("⚠️ Неправильний формат. Спробуй ще раз (приклад: <code>user@gmail.com</code>):")
        return
    
    await state.update_data(parent_email=email)
    await state.set_state(Registration.entering_parent_phone)
    await message.answer("<b>І який номер телефону в одного з твоїх батьків/опікунів?</b> Вкажи у міжнародному форматі (наприклад, +380...)")

@reg_router.message(Registration.entering_parent_phone, F.text)
async def process_parent_phone(message: Message, state: FSMContext):
    phone = message.text.strip()
    phone = '+' + phone if not phone.startswith('+') else phone
    if not re.match(PHONE_REGEX, phone):
        await message.answer("⚠️ Некоректний формат. Введи номер у міжнародному форматі (+380...):")
        return
        
    await state.update_data(parent_phone=phone)
    await state.set_state(Registration.entering_lead_source)
    await message.answer("Дякую! 😊 Залишилось всього 2 запитання, і цей розділ завершено!")
    await message.answer("Звідки ти дізнався(-лась) про Svitlo School? Обери або напиши свій варіант:", 
                         reply_markup=kb.get_lead_source_kb())

# ДЖЕРЕЛО ТРАФІКУ
@reg_router.message(Registration.entering_lead_source, F.text)
async def process_lead_source(message: Message, state: FSMContext):
    lead_source = message.text.strip()
    await state.update_data(lead_source=lead_source)
    if lead_source == "Інше":
        await message.answer("Будь ласка, коротко уточни звідки чи від кого:", reply_markup=ReplyKeyboardRemove())
    elif lead_source == "Організація":
        await message.answer("Будь ласка, уточни назву організації:", reply_markup=ReplyKeyboardRemove())   
    else:
        await state.set_state(Registration.entering_health_bool)
        await message.answer("І наостанок: чи є у тебе особливі потреби, пов’язані зі станом здоров’я або інвалідністю, про які нам варто знати для твоєї найкращої підтримки в Svitlo School? Наприклад, медичні застереження, потреби в адаптації матеріалів чи забезпеченні доступності", reply_markup=kb.get_boolean_kb())

# ЗДОРОВ'Я ТА ІНКЛЮЗІЯ
@reg_router.message(Registration.entering_health_bool, F.text)
async def process_health_bool(message: Message, state: FSMContext):
    if message.text.strip().lower() == "так":
        await state.update_data(health_bool=True)
        await state.set_state(Registration.entering_health_details)
        await message.answer("Будь ласка, опиши їх коротко (це важливо, аби могли забезпечити інклюзивне середовище):", reply_markup=ReplyKeyboardRemove())
    elif message.text.strip().lower() == "ні":
        await state.update_data(health_bool=False, health_details="")
        await _finalize_personal_data(message, state)
    else:
        await message.answer("⚠️ Будь ласка, обери «Так» або «Ні»:", reply_markup=kb.get_boolean_kb())

@reg_router.message(Registration.entering_health_details, F.text)
async def process_health_details(message: Message, state: FSMContext):
    await state.update_data(health_details=message.text.strip())
    await _finalize_personal_data(message, state)

# endregion =====================================================
# region INTERLUDE #1
# ===============================================================

async def _finalize_personal_data(message: Message, state: FSMContext):
    """Допоміжна функція: зберігає зібраний FSM-словник у Firestore та переводить на етап правил"""
    data = await state.get_data()
    student = student_ctx.get()

    if not student:
        await message.answer("⚠️ Помилка сесії: Профіль не знайдено. Надішли /start")
        return
        
    doc_id = student['id']
    await db.save_lead_profile(doc_id, data, "rules_matching")

    await state.set_state(Registration.passing_rules)
    await state.update_data(quiz_step=0)

    await message.answer(
        "✅ <b>Всі персональні дані успішно збережено!</b>\n\n"
        "Наступний крок — коротке знайомство з правилами та культурою нашої спільноти.\n"
        "📖 <a href='https://telegra.ph/Pravila-ta-kultura-Svitlo-School-07-21'>Читати повні правила (Telegraph)</a>", 
        parse_mode="HTML", 
        reply_markup=kb.get_rules_start_kb(),
        disable_web_page_preview=True
    )
    # TODO: Додати логіку надсилання квізу (Модуль 2 - Крок 3)


# endregion =====================================================
# region RULES & QUIZ
# ===============================================================

@reg_router.callback_query(Registration.passing_rules)
async def process_quiz(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    step = data.get("quiz_step", 0)
    
    if callback.data.startswith("ans_"):
        ans_idx = int(callback.data.split("_")[1])
        if ans_idx != QUIZ_DATA[step - 1]["correct"]:
            await callback.answer(
                "❌ Неправильно! Зверни увагу на правила щодо камер, відвідуваності та мови. Спробуй ще раз", 
                show_alert=True
            )
            return 
            
    if step < len(QUIZ_DATA):
        question = QUIZ_DATA[step]
        text_to_send = f"📝 <b>Check Your Rules</b>\n\n{question['q']}"
        
        if callback.data == "quiz_start":
            await callback.message.edit_text(text_to_send, reply_markup=kb.get_quiz_kb(question["options"]))
        else:
            await callback.message.edit_text(text_to_send, reply_markup=kb.get_quiz_kb(question["options"]))
            
        await state.update_data(quiz_step=step + 1)
        
    else:
        await callback.message.delete()
        await callback.message.answer(
            "🎉 <b>Супер! Ти в темі.</b>\n\n"
            "Останній крок — <b>ID Check</b>. Натисни кнопку нижче, "
            "щоб відсканувати документ. Дані не зберігаються на наших серверах.",
            reply_markup=kb.get_scanner_webapp_kb(),
            parse_mode="HTML"
        )
        await state.set_state(Registration.uploading_docs)

# endregion =====================================================
# region INTERLUDE #2
# ===============================================================

@reg_router.message(Registration.uploading_docs)
async def fallback_waiting_scan(message: Message):
    """
    Перехоплювач: спрацьовує, якщо замість WebApp юзер відправляє повідомлення або фото.
    Захищає Zero-Storage логіку.
    """
    await message.answer(
        "⚠️ Будь ласка, скористайся кнопкою <b>«📸 Level Check»</b> для безпечного сканування документа.\n\n"
        "Ми піклуємося про твої дані (Zero-Storage), тому не приймаємо фотографії безпосередньо в чат.",
        reply_markup=kb.get_scanner_webapp_kb(),
        parse_mode="HTML"
    )

# endregion =====================================================
# region ADMIN REVIEW
# ===============================================================

@reg_router.message(Registration.admin_review)
async def process_admin_review_wait(message: Message):
    await message.answer("⏳ Твоя заявка зараз перевіряється куратором. Зачекай результату")

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
    
    doc = await db.db.collection('Svitlo').document(doc_id).get()
    if not doc.exists:
        await callback.answer("Анкету не знайдено", show_alert=True)
        return
        
    data = doc.to_dict()
    health_text = f"Так ({data.get('health_issues_details')})" if data.get('health_issues_bool') else "Ні"
    
    tg_username = data.get('telegramUsername', '').replace('@', '')
    phone = data.get('phone', 'Не вказано')
    display_username = f"@{tg_username}" if tg_username else "Без юзернейму"

    # Форматування дати народження для читабельності
    dob = data.get('dateOfBirth')
    dob_str = dob.strftime("%d.%m.%Y") if hasattr(dob, 'strftime') else str(dob)

    displaced_info = f"ВПО/Біженець ({data.get('displaced_region')})" if data.get('displaced_status') else "Не ВПО/Біженець"

    detailed_text = (
        f"<b>📋 Повна анкета: {data.get('name')} {data.get('surname')}</b>\n\n"
        f"<b>Дата народження:</b> {dob_str} ({data.get('ageGroup')})\n"
        f"<b>Email:</b> <code>{data.get('email')}</code>\n"
        f"<b>Телефон:</b> <code>{phone}</code> | {display_username}\n"
        f"<b>Стать:</b> {data.get('gender')}\n"
        f"<b>Локація:</b> {data.get('city')}, {data.get('country')} | {displaced_info}\n"
        f"<b>Джерело:</b> {data.get('lead_source')}\n"
        f"<b>Проблеми зі здоров'ям:</b> {health_text}\n\n"
        f"<b>Батьки:</b> {data.get('parent_first_name')} {data.get('parent_last_name')}\n"
        f"<b>Контакти батьків:</b> <code>{data.get('parent_phone')}</code> | {data.get('parent_email')}\n\n"
        f"<i>Документ перевірено ШІ: {data.get('ai_doc_type')}</i>"
    )
    
    keyboard = kb.get_admin_action_kb(doc_id, tg_username, include_details_btn=False)
    
    await callback.answer()
    await callback.message.edit_text(detailed_text, reply_markup=keyboard)

@reg_router.callback_query(F.data.startswith("lead_confirmblock_"))
async def admin_confirm_block_lead(callback: CallbackQuery):
    doc_id = callback.data.split("_")[2]
    await callback.message.edit_reply_markup(
        reply_markup=kb.get_admin_confirm_block_kb(doc_id)
    )

@reg_router.callback_query(F.data.startswith("lead_block_"))
async def admin_block_lead(callback: CallbackQuery):
    await callback.answer("Заявку заблоковано")
    doc_id = callback.data.split("_")[2]
    
    # 1. Отримуємо документ для витягування telegramId
    doc_ref = db.db.collection('Svitlo').document(doc_id)
    doc = await doc_ref.get()
    
    if not doc.exists:
        await callback.message.edit_text(f"{callback.message.html_text}\n\n❌ <b>Помилка: Анкету не знайдено</b>")
        return

    data = doc.to_dict()
    user_id = data.get('telegramId')

    # 2. Переводимо stage в blocked у Flat Schema
    await doc_ref.update({
        "crm_stage": "blocked",
        "crm_stage_updated_at": db.get_kyivtime_now()
    })

    # 3. Гарантовано очищаємо FSM_Sessions, щоб не залишати сміття
    if user_id:
        try:
            await db.db.collection("FSM_Sessions").document(str(user_id)).delete()
        except Exception as e:
            logging.warning(f"Не вдалося видалити FSM_Session для заблокованого юзера {user_id}: {e}")

    # 4. Оновлюємо інтерфейс куратора
    reviewer_name = callback.from_user.full_name
    await callback.message.edit_text(
        f"⛔️ <b>ЗАЯКУ ВІДХИЛЕНО</b>\n"
        f"Куратор: {reviewer_name}\n\n"
        f"{callback.message.html_text}",
        parse_mode="HTML",
        reply_markup=None
    )

    # 5. Сповіщаємо спамера (опціонально)
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
    await db.db.collection('Svitlo').document(doc_id).update({
        "crm_stage": "student",
        "crm_stage_updated_at": db.get_kyivtime_now(),
        "roles": ["student"] # Надаємо базову роль
    })
    
    # 2. Оновлюємо інтерфейс куратора
    reviewer_name = callback.from_user.full_name
    await callback.message.edit_text(
        f"{callback.message.html_text}\n\n"
        f"✅ <b>ЗАРАХОВАНО!</b> (Куратор: {reviewer_name})",
        parse_mode="HTML",
        reply_markup=None # Видаляємо кнопки
    )
    
    # 3. TODO: Тут буде виклик SchoolToday API
    
    # 4. Надсилаємо студенту привітання та Lock Screen меню
    doc = await db.db.collection('Svitlo').document(doc_id).get()
    user_id = doc.to_dict().get('telegramId')
    
    # Видаляємо технічний смітник з FSM_Sessions (фінальне очищення)
    await db.db.collection("FSM_Sessions").document(str(user_id)).delete()
    
    await callback.bot.send_message(
        chat_id=user_id,
        text="🎉 <b>Вітаємо! Твою заявку схвалено.</b>\n"
             "Ти офіційно стаєш частиною SvitloSchool!\n\n"
             "Щоб розблокувати меню бота та отримати доступ до уроків, натисни кнопку нижче:",
        parse_mode="HTML",
        reply_markup=kb.get_start_menu() # Кнопка "Отримати доступ"
    )



# endregion =====================================================
# region 
# ===============================================================