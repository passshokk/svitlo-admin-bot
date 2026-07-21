# bot/reg_funnel.py
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
import re
from datetime import datetime
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.types.web_app_info import WebAppInfo
import os
from aiogram import Bot

from core import database as db
from bot import keyboards as kb
from bot.states import Registration
from core import config as cfg
from core.constants import QUIZ_DATA
from core.context import student_ctx

# Фільтр для безпечного тестування на продакшені
DEV_IDS = [1125108435]

reg_router = Router()
reg_router.message.filter(F.from_user.id.in_(DEV_IDS), F.chat.type == "private")
reg_router.callback_query.filter(F.from_user.id.in_(DEV_IDS), F.message.chat.type == "private")

# region temporary test fns
# --- ОНОВЛЕНИЙ cmd_start ---
@reg_router.message(Command("start"), F.chat.type == "private")
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
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
    await callback.message.edit_text("🔐 <b>Синхронізація акаунта</b>", parse_mode="HTML")
    await callback.message.answer("Будь ласка, напиши свою <b>електронну пошту</b>, яку ти вказував при реєстрації у SvitloSchool:", parse_mode="HTML", reply_markup=kb.get_cancel_kb())
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
        "👋 <b>Раді вітати тебе у Svitlo School!</b>\n\n"
        "Ми — освітня спільнота, що створює можливості для української молоді. "
        "Щоб доєднатися до нас та отримати доступ до уроків, потрібно заповнити заявку.\n\n"
        "<b>Що на тебе чекає:</b>\n"
        "⏱ <b>Час:</b> ~5-7 хвилин\n"
        "📝 <b>Крок 1:</b> Базові дані (ПІБ, контакти, батьки)\n"
        "🔐 <b>Крок 2:</b> Безпечна верифікація українського документа через ШІ (дані ніде не зберігаються)\n\n"
        "Готові стати частиною Svitlo?"
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
    await callback.message.edit_text("Поїхали! 🚀", reply_markup=None)
    await callback.message.answer(
        "Введи своє <b>Ім'я</b> (наприклад, Олена):", 
        parse_mode="HTML"
    )


# endregion =====================================================
# region REG FSM FUNNEL
# ===============================================================

# ІМ'Я
@reg_router.message(Registration.entering_first_name, F.text)
async def process_first_name(message: Message, state: FSMContext):
    await state.update_data(first_name=message.text.strip().title())
    await state.set_state(Registration.entering_last_name)
    await message.answer("Супер! Тепер введи своє <b>Прізвище</b> (наприклад, Коваленко):", parse_mode="HTML")

@reg_router.message(Registration.entering_last_name, F.text)
async def process_last_name(message: Message, state: FSMContext):
    await state.update_data(last_name=message.text.strip().title())
    await state.set_state(Registration.entering_email)
    await message.answer("Напиши свою <b>електронну пошту</b> (ту, якою найчастіше користуєшся):", parse_mode="HTML")

@reg_router.message(Registration.entering_email, F.text)
async def process_email(message: Message, state: FSMContext):
    email = message.text.lower().strip()
    if not re.match(cfg.EMAIL_REGEX, email):
        await message.answer("⚠️ Неправильний формат. Спробуй ще раз (приклад: <code>user@gmail.com</code>):", parse_mode="HTML")
        return
        
    await state.update_data(email=email)
    await state.set_state(Registration.entering_phone)
    await message.answer(
        "Надішли свій <b>номер телефону</b>.\nТи можеш натиснути кнопку нижче або ввести його вручну (в форматі +380XXXXXXXXX):", 
        parse_mode="HTML",
        reply_markup=kb.get_number_for_registration_kb()
    )

@reg_router.message(Registration.entering_phone, F.contact | F.text)
async def process_phone(message: Message, state: FSMContext):
    phone = message.contact.phone_number if message.contact else message.text.strip()
    phone = '+' + phone if not phone.startswith('+') else phone

    if not re.match(cfg.PHONE_REGEX, phone):
        await message.answer("⚠️ Некоректний формат.\nВведи номер у міжнародному форматі (наприклад, <code>+380991234567</code>):", parse_mode="HTML")
        return
    
    await state.update_data(phone=phone)
    await state.set_state(Registration.entering_gender)
    await message.answer("Обери свою стать:", reply_markup=kb.get_gender_kb())

@reg_router.message(Registration.entering_gender, F.text)
async def process_gender(message: Message, state: FSMContext):
    await state.update_data(gender=message.text.strip())
    await state.set_state(Registration.entering_dob)
    await message.answer("Введи свою <b>Дату народження</b> у форматі ДД.ММ.РРРР (наприклад: 15.08.2009):", parse_mode="HTML", reply_markup=ReplyKeyboardRemove())

@reg_router.message(Registration.entering_dob, F.text)
async def process_dob(message: Message, state: FSMContext):
    dob_str = message.text.strip()
    try:
        # Валідація дати та розрахунок вікової групи (ageGroup)
        dob_obj = datetime.strptime(dob_str, "%d.%m.%Y")
        age = (datetime.now() - dob_obj).days // 365
        
        if not (10 <= age <= 18):
            await message.answer("⚠️ Твій вік виходить за рамки стандартних програм Svitlo (10-13 та 14-18). Будь ласка, перевір правильність дати (ДД.ММ.РРРР)")
            return
            
        age_group = "older" if 14 <= age <= 18 else "younger" if 10 <= age <= 13 else "error"
        
        await state.update_data(dateOfBirth=dob_str, ageGroup=age_group)
        await state.set_state(Registration.entering_location)
        await message.answer("Вкажи свою нинішнє <b>локацію/місце перебування</b> (місто та країну):", parse_mode="HTML")
    except ValueError:
        await message.answer("⚠️ Неправильний формат дати. Використовуй формат ДД.ММ.РРРР (наприклад, 24.08.2008)")

@reg_router.message(Registration.entering_location, F.text)
async def process_location(message: Message, state: FSMContext):
    await state.update_data(location=message.text.strip())
    await state.set_state(Registration.entering_school)
    await message.answer("Назва твого <b>навчального закладу</b> (школа, ліцей, коледж):", parse_mode="HTML")

@reg_router.message(Registration.entering_school, F.text)
async def process_school(message: Message, state: FSMContext):
    await state.update_data(school=message.text.strip())
    await state.set_state(Registration.entering_parent_name)
    await message.answer("Вкажи <b>ПІБ одного з батьків</b> або опікуна:", parse_mode="HTML")

@reg_router.message(Registration.entering_parent_name, F.text)
async def process_parent_name(message: Message, state: FSMContext):
    await state.update_data(parent_name=message.text.strip().title())
    await state.set_state(Registration.entering_parent_email)
    await message.answer("Вкажи <b>електронну пошту</b> батьків/опікуна:", parse_mode="HTML")

@reg_router.message(Registration.entering_parent_email, F.text)
async def process_parent_email(message: Message, state: FSMContext):
    email = message.text.lower().strip()
    if not re.match(cfg.EMAIL_REGEX, email):
        await message.answer("⚠️ Неправильний формат пошти. Спробуй ще раз:")
        return
    await state.update_data(parent_email=email)
    await state.set_state(Registration.entering_parent_phone)
    await message.answer("Вкажи <b>номер телефону</b> батьків/опікуна (у форматі +380...):", parse_mode="HTML")

@reg_router.message(Registration.entering_parent_phone, F.text)
async def process_parent_phone(message: Message, state: FSMContext):
    phone = message.text.strip()
    phone = '+' + phone if not phone.startswith('+') else phone
    if not re.match(cfg.PHONE_REGEX, phone):
        await message.answer("⚠️ Некоректний формат. Введи номер у міжнародному форматі:")
        return
        
    await state.update_data(parent_phone=phone)
    await state.set_state(Registration.entering_lead_source)
    await message.answer("Звідки ти дізнався(-лась) про Svitlo School? Обери або напиши свій варіант:", 
                         reply_markup=kb.get_lead_source_kb())

@reg_router.message(Registration.entering_lead_source, F.text == "Інше")
async def process_lead_source(message: Message, state: FSMContext):
    await message.answer("Будь ласка, коротко уточни звідки чи від кого:", reply_markup=ReplyKeyboardRemove())

@reg_router.message(Registration.entering_lead_source, F.text)
async def process_lead_source(message: Message, state: FSMContext):
    await state.update_data(lead_source=message.text.strip())
    await state.set_state(Registration.entering_health_bool)
    await message.answer("Чи маєш ти проблеми зі здоров'ям, про які нам варто знати під час навчання?", reply_markup=kb.get_boolean_kb())

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
        await message.answer("⚠️ Будь ласка, обери 'Так' або 'Ні':", reply_markup=kb.get_boolean_kb())

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
    
    # Зберігаємо всі 16 полів та міняємо статус на rules_matching
    await db.save_lead_profile(doc_id, data, "rules_matching")

    await state.set_state(Registration.passing_rules)
    await state.update_data(quiz_step=0)

    await message.answer(
        "✅ <b>Всі персональні дані успішно збережено!</b>\n\n"
        "Наступний крок — коротке знайомство з правилами та культурою нашої спільноти."
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
            await callback.message.edit_text(text_to_send, reply_markup=kb.get_quiz_kb(question["options"]), parse_mode="HTML")
        else:
            await callback.message.edit_text(text_to_send, reply_markup=kb.get_quiz_kb(question["options"]), parse_mode="HTML")
            
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
# region AI WebApp for ID 
# ===============================================================

@reg_router.message(Command("test_cam"))
async def cmd_test_camera_webapp(message: Message):
    """
    Тимчасова команда для розробників. 
    Генерує кнопку з WebAppInfo для тестування фронтенду камери.
    """
    service_url = os.getenv("SERVICE_URL")
    if not service_url:
        await message.answer("⚠️ Помилка: SERVICE_URL не знайдено у змінних середовища.")
        return
        
    webapp_url = f"{service_url.rstrip('/')}/webapp/camera"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📸 Відкрити сканер", web_app=WebAppInfo(url=webapp_url))]
    ])
    
    await message.answer(
        "<b>Тест Zero-Storage Scanner</b> 🛠\n\n"
        "Натисни кнопку нижче з мобільного пристрою, щоб перевірити:\n"
        "1. Запит дозволу на камеру.\n"
        "2. Відмальовку UI (адаптивність до теми).\n"
        "3. Формування Base64 кадру.",
        parse_mode="HTML",
        reply_markup=keyboard
    )

# endregion =====================================================
# region ADMIN REVIEW
# ===============================================================

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
    
    detailed_text = (
        f"<b>📋 Повна анкета: {data.get('name')} {data.get('surname')}</b>\n\n"
        f"<b>Дата народження:</b> {data.get('dateOfBirth')} ({data.get('ageGroup')})\n"
        f"<b>Email:</b> <code>{data.get('email')}</code>\n"
        f"<b>Телефон:</b> <code>{phone}</code> | {display_username}\n"
        f"<b>Стать:</b> {data.get('gender')}\n"
        f"<b>Локація:</b> {data.get('location')}\n"
        f"<b>Навчальний заклад:</b> {data.get('ed_institution_name')}\n"
        f"<b>Джерело:</b> {data.get('lead_source')}\n"
        f"<b>Проблеми зі здоров'ям:</b> {health_text}\n\n"
        f"<b>Батьки:</b> {data.get('parent_name')}\n"
        f"<b>Контакти батьків:</b> <code>{data.get('parent_phone')}</code> | {data.get('parent_email')}\n\n"
        f"<i>Документ перевірено ШІ: {data.get('ai_doc_type')}</i>"
    )
    
    keyboard = kb.get_admin_action_kb(doc_id, tg_username, include_details_btn=False)
    
    await callback.answer()
    await callback.message.edit_text(detailed_text, parse_mode="HTML", reply_markup=keyboard)


@reg_router.callback_query(F.data == "hidden_profile_alert")
async def alert_hidden_profile(callback: CallbackQuery):
    """Показує повідомлення куратору, якщо у ліда немає юзернейму"""
    await callback.answer(
        "⚠️ У студента прихований профіль без юзернейму.\n"
        "Скористайся його номером телефону, щоб зв'язатися", 
        show_alert=True
    )


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

# @reg_router.callback_query(F.data.startswith("lead_reject_"))
# async def admin_reject_lead(callback: CallbackQuery):
    # ТУТ МАЄ БУТИ РОУТИНГ НА РІЗНІ ЕТАПИ І ПОВЕРНЕННЯ НА ДОПРАЦЮВАННЯ


    # doc_id = callback.data.split("_")[2]
    
    # doc = await db.db.collection('Svitlo').document(doc_id).get()
    # user_id = doc.to_dict().get('telegramId')

    # # Відкат статусу
    # await db.db.collection('Svitlo').document(doc_id).update({
    #     "crm_stage": "lead",
    #     "crm_stage_updated_at": db.get_kyivtime_now()
    # })

    # reviewer_name = callback.from_user.full_name
    # await callback.message.edit_text(
    #     f"{callback.message.html_text}\n\n"
    #     f"🔄 <b>ВІДХИЛЕНО / НА ДООПРАЦЮВАННЯ</b> (Куратор: {reviewer_name})",
    #     parse_mode="HTML",
    #     reply_markup=None
    # )
    
    # await callback.bot.send_message(
    #     chat_id=user_id,
    #     text="⚠️ <b>Куратор повернув твою заявку на доопрацювання.</b>\n"
    #          "З тобою незабаром зв'яжуться для уточнення деталей.",
    #     parse_mode="HTML"
    # )

# endregion =====================================================
# region 
# ===============================================================