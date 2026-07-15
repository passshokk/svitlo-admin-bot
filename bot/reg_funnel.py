# bot/reg_funnel.py
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
import re

from core import database as db
from bot import keyboards as kb
from bot.states import Registration
from core import config as cfg
from core.context import student_ctx

# Фільтр для безпечного тестування на продакшені
DEV_IDS = [1125108435]

reg_router = Router()
reg_router.message.filter(F.from_user.id.in_(DEV_IDS), F.chat.type == "private")
reg_router.callback_query.filter(F.from_user.id.in_(DEV_IDS), F.chat.type == "private")


# ---------------------------------------------------------------
# region temporary test things
# ---------------------------------------------------------------

# --- ОНОВЛЕНИЙ cmd_start ---
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    student = student_ctx.get()

    if student and student['data'].get('status') == 'student':
        # Студент вже ідентифікований (має прив'язаний telegramId)
        await message.answer(
            "Привіт! Я твій помічник у SvitloSchool ☺️\n<b>Ти вже є в загальному чаті своєї вікової групи?</b>",
            parse_mode="HTML",
            reply_markup=kb.get_start_menu()
        )
    else: 
        # Невідомий користувач (старий студент без ТГ або новий лід)
        await message.answer(
            "👋 Привіт! Я — офіційний бот Svitlo School.\n\n"
            "Обери свій статус, щоб ми могли продовжити:",
            reply_markup=kb.get_guest_start_menu()
        )

# --- РОЗГАЛУЖЕННЯ ДЛЯ СТАРИХ СТУДЕНТІВ ---
@reg_router.callback_query(F.data == "auth_existing")
async def process_auth_existing(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(Registration.waiting_email)
    await callback.message.edit_text(
        "🔐 <b>Синхронізація акаунта</b>\n\n"
        "Будь ласка, напиши свою <b>електронну пошту</b>, яку ти вказував при реєстрації у SvitloSchool:",
        parse_mode="HTML"
    )
    # Відправляємо Reply-кнопку для можливості скасування
    await callback.message.answer("Чекаю на email...", reply_markup=kb.get_cancel_kb())

# --- РОЗГАЛУЖЕННЯ ДЛЯ НОВИХ ЛІДІВ ---
@reg_router.callback_query(F.data == "auth_new_lead")
async def process_auth_new_lead(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    # Створюємо пустий документ ліда
    await db.init_lead(callback.from_user.id, callback.from_user.username)
    
    await state.set_state(Registration.entering_first_name)
    await callback.message.edit_text("👋 Чудово! Починаємо реєстрацію у Svitlo School.")
    await callback.message.answer("Введи своє <b>Ім'я</b> (наприклад, Олена):", parse_mode="HTML", reply_markup=kb.get_cancel_kb())


# endregion -----------------------------------------------------
# region REGISTRATION LINEAR FUNNEL
# ---------------------------------------------------------------

# ІМ'Я
@reg_router.message(Registration.entering_first_name, F.text)
async def process_first_name(message: Message, state: FSMContext):
    await state.update_data(first_name=message.text.strip().title())
    await state.set_state(Registration.entering_last_name)
    await message.answer("Супер! Тепер введи своє <b>Прізвище</b> (наприклад, Коваленко):", parse_mode="HTML")

# ПРІЗВИЩЕ
@reg_router.message(Registration.entering_last_name, F.text)
async def process_last_name(message: Message, state: FSMContext):
    await state.update_data(last_name=message.text.strip().title())
    await state.set_state(Registration.entering_age)
    await message.answer("Скільки тобі років? (Напиши цифрою, наприклад: 15)")

# ВІК
@reg_router.message(Registration.entering_age, F.text)
async def process_age(message: Message, state: FSMContext):
    if not message.text.isdigit() or not (10 <= int(message.text) <= 20):
        await message.answer("⚠️ Будь ласка, введи коректний вік цифрою (від 10 до 20):")
        return
        
    await state.update_data(age=int(message.text))
    await state.set_state(Registration.entering_email)
    await message.answer("Наступний крок — напиши свою <b>електронну пошту</b>:", parse_mode="HTML")

# EMAIL
@reg_router.message(Registration.entering_email, F.text)
async def process_new_email(message: Message, state: FSMContext):
    email = message.text.lower().strip()
    if not re.match(cfg.EMAIL_REGEX, email):
        await message.answer("⚠️ Неправильний формат. Спробуй ще раз (приклад: <code>user@gmail.com</code>):", parse_mode="HTML")
        return
        
    await state.update_data(email=email)
    await state.set_state(Registration.entering_phone)
    # Відправляємо клавіатуру з кнопкою request_contact
    await message.answer(
        "І останнє: надішли свій номер телефону.\nТи можеш натиснути кнопку нижче або ввести його вручну (в форматі +380XXXXXXXXX)", 
        reply_markup=kb.get_contact_kb()
    )

# ТЕЛЕФОН (Обробка контакту або тексту)
@reg_router.message(Registration.entering_phone, F.contact | F.text)
async def process_phone(message: Message, state: FSMContext):
    # Якщо юзер натиснув кнопку
    if message.contact:
        phone = message.contact.phone_number
        phone = '+' + phone if not phone.startswith('+') else phone
    # Якщо ввів вручну
    else:
        phone = message.text.strip()
        # Міжнародний стандарт E.164: + та 8-15 цифр
        if not re.match(cfg.PHONE_REGEX, phone):
            await message.answer(
                "⚠️ Некоректний формат.\nВведи номер у міжнародному форматі, починаючи з плюса і коду країни (наприклад, <code>+380991234567</code>):", 
                parse_mode="HTML"
            )
            return
    
    data = await state.get_data()
    data['phone'] = phone
    
    student = student_ctx.get()
    doc_id = student['id'] if student else str(message.from_user.id)
    
    # Зберігаємо дані в корінь і чистимо клавіатуру
    await db.save_lead_profile(doc_id, data, "rules_matching")
    await state.set_state(Registration.passing_rules)
    
    # Видаляємо Reply-клавіатуру запиту контакту
    await message.answer("✅ Дані збережено! Переходимо до знайомства з культурою школи...", reply_markup=ReplyKeyboardRemove())

# endregion -----------------------------------------------------
# region
# ---------------------------------------------------------------   