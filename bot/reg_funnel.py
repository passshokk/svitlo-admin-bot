# bot/registration.py
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
import re

from core import database as db
from bot import keyboards as kb
from bot.states import Registration
from core import config as cfg

reg_router = Router()

# Фільтр для безпечного тестування на продакшені
DEV_IDS = [1125108435]

reg_router.message.filter(F.from_user.id.in_(DEV_IDS), F.chat.type == "private")
reg_router.callback_query.filter(F.from_user.id.in_(DEV_IDS), F.chat.type == "private")


# ---------------------------------------------------------------
# region temporary test things
# ---------------------------------------------------------------

# ОНОВЛЕНИЙ cmd_start
@reg_router.message(Command("start"), F.chat.type == "private")
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    # Перевірка поточного статусу в базі
    student_doc = await db.get_student_by_tg_id(message.from_user.id)
    await message.answer(
            "Привіт! Я твій помічник у SvitloSchool ☺️\n<b>Ти вже є в загальному чаті своєї вікової групи?</b>",
            parse_mode="HTML",
            reply_markup=kb.get_start_menu()
            )

    if student_doc and student_doc['data'].get('status') == 'student':
        # Вже студент
        await message.answer(
            "Привіт! Я твій помічник у SvitloSchool ☺️\n<b>Ти вже є в загальному чаті своєї вікової групи?</b>",
            parse_mode="HTML",
            reply_markup=kb.get_start_menu()
        )
    else:
        # Новий лід
        await db.init_lead(message.from_user.id, message.from_user.username)
        await state.set_state(Registration.entering_full_name)
        await message.answer("👋 Привіт! Починаємо реєстрацію у Svitlo School.\n\nВведи своє <b>Ім'я та Прізвище</b>:", parse_mode="HTML")

# endregion -----------------------------------------------------
# region REGISTRATION LINEAR FUNNEL
# ---------------------------------------------------------------

@reg_router.message(Registration.entering_full_name, F.text)
async def process_full_name(message: Message, state: FSMContext):
    await state.update_data(full_name=message.text.strip().title())
    await state.set_state(Registration.entering_age)
    await message.answer("Чудово! Скільки тобі років? (Напиши цифрою, наприклад: 15)")

@reg_router.message(Registration.entering_age, F.text)
async def process_age(message: Message, state: FSMContext):
    if not message.text.isdigit() or not (10 <= int(message.text) <= 20):
        await message.answer("⚠️ Будь ласка, введи коректний вік цифрами (від 10 до 20):")
        return
        
    await state.update_data(age=int(message.text))
    await state.set_state(Registration.entering_email)
    await message.answer("Наступний крок: напиши свою <b>електронну пошту</b>", parse_mode="HTML")

@reg_router.message(Registration.entering_email, F.text)
async def process_new_email(message: Message, state: FSMContext):
    email = message.text.lower().strip()
    if not re.match(cfg.EMAIL_REGEX, email):
        await message.answer("⚠️ Це не схоже на email. Правильний формат: <code>user@gmail.com</code>. Спробуй ще раз!", parse_mode="HTML")
        return
        
    await state.update_data(email=email)
    await state.set_state(Registration.entering_phone)
    await message.answer("І останнє: надішли свій номер телефону (у форматі +380...)")

@reg_router.message(Registration.entering_phone, F.text)
async def process_phone(message: Message, state: FSMContext):
    phone = message.text.strip()
    # Можна додати регулярку на перевірку формату телефону
    
    data = await state.get_data()
    data['phone'] = phone
    
    # 1. Записуємо профіль у чистий об'єкт та апдейтимо етап CRM
    await db.save_lead_profile(message.from_user.id, data, "applicant_form_done")
    
    # 2. Переводимо FSM на опитування (наступний модуль)
    await state.set_state(Registration.passing_rules)
    
    # TODO: Тут відправляємо pre-recorded Video Note від команди
    await message.answer("✅ Дані збережено! Переходимо до знайомства з культурою школи...")

# endregion -----------------------------------------------------
# region
# ---------------------------------------------------------------   