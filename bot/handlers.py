# bot/handlers.py
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove, ReactionTypeEmoji, LinkPreviewOptions
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
import re
from datetime import timedelta, datetime
from zoneinfo import ZoneInfo
from uvicorn import logging

from bot.middleware import RequireAuthMiddleware
from core.context import student_ctx, user_roles_ctx
from bot.states import TicketFSM, Registration
from core import rbuddy_data as rb
from core import prefect_data as pr
from core import database as db
from bot import keyboards as kb
from core import utils as ut
from core import config as cfg
from api.task_manager import enqueue_task
from bot.reg_funnel import reg_router
from bot.filters import ActiveTicketFilter, IsDevFilter

# region ROUTER --------------------------------

dev_router = Router()
private_router = Router()
public_router = Router()
fallback_router = Router()
support_router = Router()

private_router.message.filter((F.chat.type == "private") | (F.chat.id == cfg.CURATOR_GROUP_ID))
public_router.message.filter((F.chat.type == "private") | (F.chat.id == cfg.CURATOR_GROUP_ID))
private_router.callback_query.filter((F.message.chat.type == "private") | (F.message.chat.id == cfg.CURATOR_GROUP_ID))
public_router.callback_query.filter((F.message.chat.type == "private") | (F.message.chat.id == cfg.CURATOR_GROUP_ID))
# Фільтр: пускати в dev_router ТІЛЬКИ розробників
dev_router.message.filter(IsDevFilter(), F.chat.type == "private")
dev_router.callback_query.filter(IsDevFilter(), F.message.chat.type == "private")

private_router.message.middleware(RequireAuthMiddleware())
private_router.callback_query.middleware(RequireAuthMiddleware())

# MAIN ROUTER AGGREGATOR & HIERARCHY
tg_router = Router()

#1. Розробницький роутер (для тестів)
tg_router.include_router(dev_router)

# 2. Воронка реєстрації - поки на тесті
tg_router.include_router(reg_router)

# 3. ПРИВАТНИЙ: Лише авторизовані студенти
tg_router.include_router(private_router)

# 4. ПУБЛІЧНИЙ: Доступний для всіх
tg_router.include_router(public_router)

# 5. ПІДТРИМКА: Доступний для всіх, але з обмеженнями
tg_router.include_router(support_router)

# 6. СТРОГО ОСТАННІМ: Фолбеки (невідомі команди, незрозумілий текст)
tg_router.include_router(fallback_router)


# endregion =====================================================
# region ADMIN: Dev Access Management
# ===============================================================
# /adddev, /removedev: дев кидає юзера через нативний пікер Telegram (без потреби мати його в контактах)

_DEV_ADD_REQUEST_ID = 1001
_DEV_REMOVE_REQUEST_ID = 1002

@dev_router.message(Command("adddev"), F.from_user.id == cfg.OWNER_ID)
async def cmd_add_dev(message: Message):
    await message.answer(
        "Обери користувача, якого зробити розробником:",
        reply_markup=kb.get_user_picker_kb(_DEV_ADD_REQUEST_ID)
    )

@dev_router.message(Command("removedev"), F.from_user.id == cfg.OWNER_ID)
async def cmd_remove_dev(message: Message):
    await message.answer(
        "Обери користувача, якого прибрати зі списку розробників:",
        reply_markup=kb.get_user_picker_kb(_DEV_REMOVE_REQUEST_ID)
    )

@dev_router.message(F.users_shared, F.from_user.id == cfg.OWNER_ID)
async def handle_dev_user_shared(message: Message):
    shared = message.users_shared
    target = shared.users[0]

    username_part = f" (@{target.username})" if target.username else " (без юзернейму)"

    if shared.request_id == _DEV_ADD_REQUEST_ID:
        await db.add_dev_id(target.user_id, target.username)
        await message.answer(f"✅ Додано розробника: <code>{target.user_id}</code>{username_part}", reply_markup=ReplyKeyboardRemove())
    elif shared.request_id == _DEV_REMOVE_REQUEST_ID:
        await db.remove_dev_id(target.user_id)
        await message.answer(f"🗑️ Прибрано з розробників: <code>{target.user_id}</code>{username_part}", reply_markup=ReplyKeyboardRemove())

# endregion =====================================================
# region COMMANDS
# ===============================================================

@public_router.message(Command("start"), F.chat.type == "private")
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Привіт! Я твій помічник у SvitloSchool ☺️\n<b>Ти вже є в загальному чаті своєї вікової групи?</b>",
        parse_mode="HTML",
        reply_markup=kb.get_start_menu()
    )

@public_router.message(Command("menu"), F.chat.type == "private")
async def cmd_menu(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Вітаю у SvitloMenu! Обирай:",
        reply_markup=kb.get_main_menu()
    )

@private_router.message(Command("profile"), F.chat.type == "private")
async def cmd_profile(message: Message, state: FSMContext):
    await state.clear()
    student = student_ctx.get()

    text = ut.get_profile_text(student['data'])
    await message.answer(text)

@public_router.message(Command("prefect"))
async def handle_prefect_check(message: Message):
    await message.answer("Ну ти олдятіна))")

@private_router.message(Command("house"), F.chat.type == "private")
async def cmd_house_smart_access(message: Message, state: FSMContext):
    await state.clear()
    student = student_ctx.get()
    data = student['data']
    house_name = data.get("house")
    
    if not house_name or house_name == "Newbie":
        await message.answer("🌱 Оскільки ти нещодавно з нами, ти ще ймовірно <b>не був розподілений у свій Хаус.</b> Очікуй на івент призначення нових учасників у Хауси впродовж цього семестру!")
        return

    if data.get("hasHouseAccess", False):
        await message.answer("⚠️ <b>Доступ до групи вже було надано.</b>\nЯкщо група загубилась, напиши хаус-кураторці", reply_markup=kb.get_sasha_curator_keyboard())
        return

    target_chat_id = cfg.HOUSE_CHATS.get(house_name)
    if not target_chat_id:
        await message.answer(f"❌ Твій хаус ({house_name}) знайдено, але група ще не налаштована. Звернись до куратора.", reply_markup=kb.get_pasha_curator_keyboard())
        return

    try:
        invite = await message.bot.create_chat_invite_link(
            chat_id=target_chat_id, member_limit=1
        )
        
        await db.grant_house_access(student['id'])
        await message.answer(
            f"🎉 Тобі надано доступ в <b>{house_name}</b>!\n\n"
            f"Ось твоє персональне одноразове посилання:\n{invite.invite_link}", 
            parse_mode="HTML"
        )
        
        await message.answer("Повертаємось у SvitloMenu:", reply_markup=kb.get_main_menu())
        
    except Exception as e:
        await message.answer(
            "❌ Помилка при генерації посилання. Бот має бути адміном у групі.", 
            reply_markup=kb.get_pasha_curator_keyboard()
        )
        print(f"Error generating house link: {e}")

# endregion =====================================================
# region CALLBACKS
# ===============================================================

@public_router.callback_query(F.data == "get_gengroup_access")
async def reg_for_access(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    await callback.answer()
    await state.set_state(Registration.waiting_email)
    await state.update_data(emailFlowSource="get_gengroup_access_btn")
    await callback.message.edit_text("🔐 <b>Процес отримання доступу до групи</b>")
    await callback.message.answer(
        "Будь ласка, напиши свою <b>електронну пошту</b>, яку ти вказував при реєстрації в SvitloSchool:",
        parse_mode="HTML",
        reply_markup=kb.get_email_cancel_kb()
    )

@public_router.callback_query(F.data == "verify")
async def verify_for_access(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    student = student_ctx.get()

    # 1. Юзера взагалі немає в БД (старий зі SchoolToday) -> Відправляємо на лінковку
    if not student:
        await state.set_state(Registration.waiting_email)
        await state.update_data(emailFlowSource="verify_btn_no_student")
        await callback.message.edit_text("<b>🔐 Щоб користуватись повним функціоналом, синхронізуй акаунт</b>")
        await callback.message.answer("Напиши свою <b>електронну пошту</b>, яку ти вказував при реєстрації у SvitloSchool:", reply_markup=kb.get_email_cancel_kb())
        return
    
    # 2. Юзер - повноцінний студент або стаф -> Пускаємо в меню
    await callback.message.edit_text("Вітаю у SvitloMenu! Обирай:", reply_markup=kb.get_main_menu())

@public_router.callback_query(F.data == "main_menu")
async def clbck_menu(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        "Вітаю у SvitloMenu! Обирай:",
        reply_markup=kb.get_main_menu()
    )

@private_router.callback_query(F.data == "my_profile")
async def clbck_profile(callback: CallbackQuery):
    student = student_ctx.get()
    text = ut.get_profile_text(student['data'])
    await callback.message.edit_text(text, reply_markup=kb.get_back_to_menu_kb())

@private_router.callback_query(F.data == "house")
async def clbck_house_smart_access(callback: CallbackQuery):
    await callback.answer()
    student = student_ctx.get()
    data = student['data']
    house_name = data.get("house")
    
    if not house_name or house_name == "Newbie":
        await callback.message.edit_text("🌱 Оскільки ти нещодавно з нами, ти ще ймовірно <b>не був розподілений у свій Хаус.</b> Очікуй на івент призначення нових учасників у Хауси впродовж цього семестру!", reply_markup=kb.get_main_menu())
        return

    if data.get("hasHouseAccess", False):
        await callback.message.edit_text("⚠️ <b>Доступ до групи вже було надано.</b>\nЯкщо група загубилась, напиши хаус-кураторці", reply_markup=kb.get_sasha_curator_keyboard())
        return

    target_chat_id = cfg.HOUSE_CHATS.get(house_name)
    if not target_chat_id:
        await callback.message.edit_text(f"❌ Твій хаус ({house_name}) знайдено, але група ще не налаштована. Звернись до куратора.", reply_markup=kb.get_pasha_curator_keyboard())
        return

    try:
        invite = await callback.message.bot.create_chat_invite_link(
            chat_id=target_chat_id, member_limit=1
        )
        
        await db.grant_house_access(student['id'])
        await callback.message.edit_text(
            f"🎉 Тобі надано доступ в <b>{house_name}</b>!\n\n"
            f"Ось твоє персональне одноразове посилання:\n{invite.invite_link}", 
            parse_mode="HTML"
        )
        
        await callback.message.answer("Повертаємось у SvitloMenu:", reply_markup=kb.get_main_menu())
        
    except Exception as e:
        await callback.message.edit_text(
            "❌ Помилка при генерації посилання. Бот має бути адміном у групі.", 
            reply_markup=kb.get_pasha_curator_keyboard()
        )
        print(f"Error generating house link: {e}")

@public_router.callback_query(F.data == "socials")
async def show_socials(callback: CallbackQuery):
    await callback.answer()

    spacer = "⠀" * 6
    await callback.message.edit_text(
        f"<b>Соцмережі SvitloSchool:</b> {spacer}",
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=kb.get_socials_kb()
    )

@public_router.callback_query(F.data == "support_menu")
async def start_support_inline(callback: CallbackQuery, state: FSMContext):
    active_ticket = await db.get_active_ticket(callback.from_user.id)
    if active_ticket:
        await callback.answer("Ти вже маєш відкритий запит! 😉 Пиши прямо сюди, у чат", show_alert=True)
        return

    await callback.answer()    
    await state.set_state(TicketFSM.choosing_category)
    await callback.message.answer(
        "<b>🌟 Svitlo Help Centre</b>\n"
        "Вибирай категорію свого запиту:", 
        parse_mode="HTML",
        reply_markup=kb.get_categories_kb()
    )

@public_router.callback_query(F.data.startswith("take_"))
async def curator_takes_ticket(callback: CallbackQuery):
    ticket_id = callback.data.split("_")[1]
    
    chat_member = await callback.bot.get_chat_member(
        chat_id=callback.message.chat.id, 
        user_id=callback.from_user.id
    )
    title = getattr(chat_member, 'custom_title', 'Curator Oleg')
    tag = getattr(chat_member, 'tag', 'Curator Oleg')
    curator_title = title or tag
    
    curator_name = f"{curator_title}" if curator_title else callback.from_user.full_name
    
    await callback.answer(f"{curator_name}, тікет #{int(ticket_id):05} тепер за тобою!")
    await db.assign_curator(ticket_id, curator_name)
    # Блокуємо кнопку для інших кураторів
    await callback.message.edit_reply_markup(reply_markup=kb.get_taken_ticket_kb(ticket_id,curator_name))
    
    ticket_data = await db.get_ticket(ticket_id)
    if ticket_data:
        user_id = ticket_data['student_id']
        await callback.bot.send_message(
        chat_id=user_id,
        text=f"🟢 На зв'язку <b>{curator_name}</b>. Уже беру твій запит у роботу й скоро відповім!",
        parse_mode="HTML"
    )

@public_router.callback_query(F.data.startswith("close_"))
async def inline_close_ticket(callback: CallbackQuery):
    ticket_id = callback.data.split("_")[1]
    ticket_data = await db.get_ticket(ticket_id)
    
    if not ticket_data or ticket_data['status'] == 'closed':
        await callback.answer("⚠️ Цей тікет вже закритий!", show_alert=True)
        return

    # 🛡 ЩИТ: Перевіряємо, чи клікає ТОЙ САМИЙ куратор
    assigned_curator = ticket_data.get('curator_name')
    chat_member = await callback.bot.get_chat_member(
        chat_id=callback.message.chat.id, 
        user_id=callback.from_user.id
    )
    title = getattr(chat_member, 'custom_title', 'Curator Oleg')
    tag = getattr(chat_member, 'tag', 'Curator Oleg')
    curator_title = title or tag
    
    current_clicker_name = f"{curator_title}" if curator_title else callback.from_user.full_name

    if assigned_curator != current_clicker_name:
        await callback.answer("⛔️ Тільки куратор, що веде цей тікет, може його закрити!", show_alert=True)
        return
    # ================================================

    await db.close_ticket(ticket_id)
    old_html = callback.message.html_text
    new_html = old_html.replace("Новий тікет", "✅ <b>ЗАКРИТИЙ тікет</b>")
    await callback.message.edit_text(
        text=new_html,
        reply_markup=kb.get_closed_ticket_kb(assigned_curator),
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )
    await callback.answer("🔒 Тікет успішно закрито!")

    user_id = ticket_data['student_id']
    await callback.bot.send_message(
        chat_id=user_id,
        text="<b>✨ Ми розібралися з твоїм запитом і закриваємо його. Дякую за звернення!</b>\n\n"
            f"Будь ласка, оціни роботу куратора {assigned_curator}:",
        parse_mode="HTML",
        reply_markup=kb.get_nps_kb(ticket_id)
    )

@public_router.callback_query(F.data.startswith("nps_"))
async def process_nps(callback: CallbackQuery):
    _, ticket_id, rating_str = callback.data.split("_")
    rating = int(rating_str)
    updated_ticket_data = await db.set_ticket_rating(ticket_id, rating)
    await callback.message.edit_text(f"<b>Дякую за твою оцінку — {rating} ⭐</b>")
    await callback.message.answer("Повертаємось у SvitloMenu:", reply_markup=kb.get_main_menu())

    # Функція експорту в Notion
    await enqueue_task("/tasks/export_notion", payload=updated_ticket_data)

# endregion =====================================================
# region CALLBACKS - RB
# ===============================================================

@private_router.callback_query(F.data.startswith("rb_day:"))
async def switch_rbuddy_day(callback: CallbackQuery):
    await callback.answer()
    
    day_index = int(callback.data.split(":")[1])
    day_name = rb.DAYS_INTEXT[day_index]
    
    text = f"<b>📚 Розклад Reading Buddies на {day_name}.</b>\nОбирай та натискай, до якого Buddy хочеш доєднатись в тг-групу:"
    keyboard = rb.get_rbuddy_day_keyboard(day_index)

    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except Exception:
        pass

@private_router.callback_query(F.data.startswith("no_url:"))
async def handle_missing_url(callback: CallbackQuery):
    status = callback.data.split(":")[1]
    
    if status == "platform":
        text = "Спілкуємося на платформі"
    else:
        text = "Посилання на цю групу ще не додано"

    await callback.answer(text, show_alert=True)

# endregion =====================================================
# region CALLBACKS - PREF
# ===============================================================

@private_router.callback_query(F.data == "pref_group")
async def show_prefect_schedule_auto(callback: CallbackQuery):
    await callback.answer()
    student = student_ctx.get()
    group = student['data'].get("ageGroup")
    group_name = "старшої" if group == "older" else "молодшої"
    
    today_index = datetime.now(ZoneInfo("Europe/Kyiv")).weekday()
    day_name = pr.DAYS_INTEXT[int(today_index)]

    text = f"<b>🎓 Розклад уроків {group_name} групи на {day_name}.</b>\nОбирай предмет, щоб сконтактувати з його префектом:"
    keyboard = pr.get_prefects_day_keyboard(int(today_index), group)
    await callback.message.edit_text(text, reply_markup=keyboard)

@private_router.callback_query(F.data.startswith("oldpref_day:") | F.data.startswith("ypref_day:"))
async def switch_prefect_day(callback: CallbackQuery):
    await callback.answer()

    action, day_index = callback.data.split(":")
    day_name = pr.DAYS_INTEXT[int(day_index)]
    group = "older" if action == "oldpref_day" else "younger"
    group_name = "старшої" if group == "older" else "молодшої"

    text = f"<b>🎓 Розклад уроків {group_name} групи на {day_name}.</b>\nОбирай предмет, щоб сконтактувати з його префектом:"
    keyboard = pr.get_prefects_day_keyboard(int(day_index), group)
    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except Exception:
        pass
    
@private_router.callback_query(F.data.startswith("oldpref_sel:") | F.data.startswith("ypref_sel:"))
async def show_prefect_info(callback: CallbackQuery):
    await callback.answer()
    action, day_idx, lesson_idx = callback.data.split(":")
    day_name = pr.DAYS_UA[int(day_idx)]

    if action == "oldpref_sel": group = "older"
    elif action == "ypref_sel": group = "younger"
    TGT_SCH = pr.SCHEDULE_MAPPING[group]["schedule"]
    data = TGT_SCH[day_name][int(lesson_idx)]
    
    if data['username']:
        text = (
            f"<b>Контакт префекта для уроку «{data['lesson_full']}»:</b>\n"
            f"👤 {data['prefect']} — {data['username']}\n\n"
            f"ℹ️ Напиши префекту, щоб попередити про відсутність або якщо є питання щодо уроку"
        )
    elif data['prefect']:
        text = (
            f"<b>Префект уроку «{data['lesson_full']}»:</b>\n"
            f"👤 {data['prefect']}\n\n"
            f"⚠️ Тг-нікнейм не надано, повідом про відсутність у групі."
        )
    else:
        text = (
            f"<b>Урок: «{data['lesson_full']}»</b>\n"
            f"⚠️ Наразі ця позиція префекта відкрита. Повідом про відсутність у групі."
        )
    
    back_action = pr.SCHEDULE_MAPPING[group]["cb_data"]
    back_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад до розкладу", callback_data=f"{back_action}:{day_idx}")]
    ])
    
    await callback.message.edit_text(text, reply_markup=back_keyboard)

# endregion =====================================================
# region FSM (Messages)
# ===============================================================

@public_router.message(StateFilter(TicketFSM), F.text.in_(["🔙 Назад у меню", "Скасувати"]))
async def cancel_ticket_fsm(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Створення запиту скасовано 👌", reply_markup=ReplyKeyboardRemove())
    await message.answer("Повертаємось у SvitloMenu:", reply_markup=kb.get_main_menu())

@public_router.message(TicketFSM.choosing_category, F.text.in_(["Технічні баги", "Освітній процес", "Організаційні питання"]))
async def category_chosen(message: Message, state: FSMContext):
    await state.update_data(category=message.text)
    await state.set_state(TicketFSM.writing_first_message)
    await message.answer(
        "<b>Розкажи, що трапилося 👀</b>\n"
        "<i>Можеш надсилати не лише текст, а голосові, фото чи відео:</i>", 
        parse_mode="HTML",
        reply_markup=kb.get_ticket_cancel_kb()
    )

@public_router.message(TicketFSM.choosing_category)
async def category_fallback(message: Message):
    await message.answer("Будь ласка, вибери категорію кнопками нижче 👇")

@public_router.message(TicketFSM.writing_first_message)
async def first_ticket_message(message: Message, state: FSMContext):
    data = await state.get_data()
    category = data['category']
    text_content = message.text or message.caption or "[Медіафайл]"
    
    student_id = message.from_user.id
    student_name = message.from_user.full_name
    username = message.from_user.username
    if username:
        student_display = f'<a href="https://t.me/{username}">{student_name}</a>'
    else:
        student_display = f"<b>{student_name}</b> (без юзернейму) <code>{student_id}</code>"

    thread_id = cfg.CATEGORY_THREADS.get(category)

    alert_template = (
        f"<b>Новий тікет[TICKET_ID]!</b>\n"
        f"<b>📚 Категорія:</b> {category}\n"
        f"<b>👤 Студент:</b> {student_display}\n"
        f"<b>🆘 Опис запиту:</b>\n{text_content}"
    )

    group_msg = await message.bot.send_message(
        chat_id=cfg.CURATOR_GROUP_ID,
        message_thread_id=thread_id,
        text=alert_template.replace("[TICKET_ID]", ""),
        parse_mode="HTML",
        reply_markup=kb.get_take_ticket_kb("temp"),
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )
    ticket_id = group_msg.message_id

    # Оновлюємо текст і кнопку, додаючи реальний ID тікета
    await group_msg.edit_text(
        text=alert_template.replace("[TICKET_ID]", f" <code>#{ticket_id:05}</code>"),
        parse_mode="HTML",
        reply_markup=kb.get_take_ticket_kb(str(ticket_id)),
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )
    await db.create_ticket(ticket_id, message.from_user.id, category, text_content)
    logging.info(f"Ticket #{ticket_id} created by user {message.from_user.id}")
    
    # фоновий таск на нагадування
    await enqueue_task(
        endpoint="/tasks/sla_check",
        payload={"ticket_id": str(ticket_id), "category": category},
        delay_seconds=600
    )

    if not message.text:
        await message.copy_to(chat_id=cfg.CURATOR_GROUP_ID, reply_to_message_id=ticket_id)
    
    await state.clear()
    await message.answer("<b>✅ Твій запит уже летить до кураторів!</b> Шукаємо вільного...")

@public_router.message(Registration.waiting_email, F.text.in_(["🚫 Скасувати введення", "Скасувати"]))
async def cancel_email_input(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Введення пошти скасовано 👌", reply_markup=ReplyKeyboardRemove())
    await message.answer("⚠️ Зауваж, якщо ти не синхронізуєш акаунт, ти не зможеш користуватись повним функціоналом бота!\nЗа допомогою звернись у /help")

@public_router.message(Registration.waiting_email, F.text)
async def process_email_input(message: Message, state: FSMContext):
    user_id = message.from_user.id
    email = message.text.lower().strip()
    if not re.match(cfg.EMAIL_REGEX, email):
        await message.answer(
            "<b>Іу, це не схоже на email.. Спробуй ще раз!</b>\n"
            "Правильний формат: <code>user@gmail.com</code>",
            parse_mode="HTML"
        )
        return # Стан залишається, чекаємо далі

    student = await db.get_student_by_email(email)
    if not student:
        await message.answer(
            "<b>❗️ Хм, такий email не знайдено.</b>\n"
            "Перевір, чи немає помилки, або звернись до куратора ⬇️",
            parse_mode="HTML",
            reply_markup=kb.get_pasha_curator_keyboard()
        )
        return
        
    data = student['data']
    if data.get("hasGroupAccess") is True:
        if not data.get("telegramId") or data.get("telegramId") == 0:
            await db.link_telegram_id(student['id'], user_id)

            student_ctx.set(student)
            user_roles_ctx.set(data.get('roles', []))

            await message.answer("✅ <b>Твій акаунт успішно синхронізовано</b>", reply_markup=ReplyKeyboardRemove())
            await message.answer("<b>Вітаю у SvitloMenu!</b> Вибирай:", reply_markup=kb.get_main_menu())
        else:
            await message.answer("<b>⚠️ Доступ до групи вже було надано.</b>", reply_markup=kb.get_back_to_menu_kb())
        await state.clear()
        return
        
    age_value = data.get("ageGroup")
    target_chat_id = cfg.GROUPS_MAPPING.get(age_value)
    if not target_chat_id:
        await message.answer("❌ Не вдалося визначити твою вікову групу", reply_markup=kb.get_pasha_curator_keyboard())
        await state.clear()
        return
        
    try:
        invite = await message.bot.create_chat_invite_link(
            chat_id=int(target_chat_id), member_limit=1, expire_date=timedelta(days=1)
        )
        await db.grant_access_to_student(student['id'], user_id)

        student_ctx.set(student)
        user_roles_ctx.set(data.get('roles', []))

        await state.clear()
        
        raw_name = data.get("firstName", "Учень")
        name = str(raw_name).strip().title()
        await message.answer(
            f"<b>✅ Вітаю, {name}! Твій акаунт успішно зареєстровано.</b>\n\n"
            f"<b>Твоє одноразове посилання: {invite.invite_link}</b>\n"
            "Зауваж, воно діє лише 1 день.",
            parse_mode="HTML", reply_markup=ReplyKeyboardRemove()
        )
        
        await message.answer("<b>Це — SvitloMenu!</b> Вибирай потрібний пункт:", reply_markup=kb.get_main_menu())
        
    except Exception as e:
        await message.answer("❌ Технічна помилка при генерації посилання", reply_markup=kb.get_pasha_curator_keyboard())
        print(f"ERROR: {e}")

# endregion =====================================================
# region HELP CENTRE
# ===============================================================

@support_router.message(F.chat.type == "private", ActiveTicketFilter())
async def user_follow_up_message(message: Message, active_ticket: dict):
    # active_ticket прилітає напряму з фільтра
    ticket_id = active_ticket['ticket_id']
    text_content = message.text or message.caption or "[Медіафайл]"
    await db.append_user_message(ticket_id, text_content)

    student_name = message.from_user.full_name
    if message.text:
        await message.bot.send_message(
            chat_id=cfg.CURATOR_GROUP_ID,
            text=f"<code>#{int(ticket_id):05}</code>, <b>{student_name}:</b>\n{message.text}",
            parse_mode="HTML",
            reply_to_message_id=ticket_id
        )
    else:
        custom_caption = f"<code>#{int(ticket_id):05}</code>, <b>{student_name}:</b>\n{message.caption}" if message.caption else f"<code>#{int(ticket_id):05}</code>, <b>{student_name}</b> надіслав(ла) файл"
        try:
            await message.copy_to(
                chat_id=cfg.CURATOR_GROUP_ID,
                caption=custom_caption,
                parse_mode="HTML",
                reply_to_message_id=ticket_id
            )
        except Exception:
            # Якщо це стікер або "кружечок"
            await message.bot.send_message(
                chat_id=cfg.CURATOR_GROUP_ID, 
                text=f"<code>#{int(ticket_id):05}</code>, <b>{student_name}:</b>", 
                parse_mode="HTML",
                reply_to_message_id=ticket_id
            )
            await message.copy_to(
                chat_id=cfg.CURATOR_GROUP_ID,
                reply_to_message_id=ticket_id
            )

@support_router.message(F.chat.id == cfg.CURATOR_GROUP_ID, F.reply_to_message)
async def curator_reply_handler(message: Message):
    ticket_id = message.reply_to_message.message_id
    ticket_data = await db.get_ticket(ticket_id)
    if not ticket_data:
        return
    
    if ticket_data['status'] == 'closed':
        await message.reply(f"⚠️ Тікет <code>#{int(ticket_id):05}</code> уже закритий")
        return

    # ==========================================
    # 🛡 ЩИТ: ПЕРЕВІРКА ПРАВ НА ВІДПОВІДЬ
    # ==========================================
    
    chat_member = await message.bot.get_chat_member(
        chat_id=message.chat.id, 
        user_id=message.from_user.id
    )
    title = getattr(chat_member, 'custom_title', 'Curator Oleg')
    tag = getattr(chat_member, 'tag', 'Curator Oleg')
    curator_title = title or tag

    current_sender_name = f"{curator_title}" if curator_title else message.from_user.full_name
    assigned_curator = ticket_data.get('curator_name')

    if not assigned_curator:
        warn_msg = await message.reply("🔻 <b>Помилка:</b>\nспочатку натисни кнопку «Взяти в роботу» під цим тікетом")
        # Відправляємо задачу в Cloud Tasks для неблокуючого видалення
        await enqueue_task(
            endpoint="/tasks/delete_messages",
            payload={
                "chat_id": message.chat.id, 
                "message_ids": [warn_msg.message_id, message.message_id]
            },
            delay_seconds=5
        )
        return

    if assigned_curator != current_sender_name:
        await message.react(reaction=[ReactionTypeEmoji(emoji="👎")])
        return

    # ==========================================

    user_id = ticket_data['student_id']
    curator_name = assigned_curator

    # /close
    if message.text and message.text.lower().strip() == "/close":
        await db.close_ticket(ticket_id)

        old_html = message.reply_to_message.html_text
        new_html = old_html.replace("Новий тікет", "✅ <b>ЗАКРИТИЙ тікет</b>")
        try:
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=ticket_id,
                text=new_html,
                parse_mode="HTML",
                reply_markup=kb.get_closed_ticket_kb(curator_name),
                link_preview_options=LinkPreviewOptions(is_disabled=True)
            )
        except Exception as e:
            print(f"Не вдалося оновити текст тікета: {e}")
            
        await message.reply(f"🔒 Тікет <code>#{int(ticket_id):05}</code> успішно закрито")

        await message.bot.send_message(
            chat_id=user_id,
            text="<b>✨ Ми розібралися з твоїм запитом і закриваємо його. Дякую за звернення!</b>\n\n"
                f"Будь ласка, оціни роботу куратора {curator_name}:",
            parse_mode="HTML",
            reply_markup=kb.get_nps_kb(ticket_id)
            )
        return
    
    # звичайна відповідь куратора
    text_content = message.text or message.caption or "[Медіафайл]"
    await db.append_curator_message(ticket_id, text_content)

    # відправка юзеру (з підтримкою медіа)
    if message.text:
        await message.bot.send_message(
            chat_id=user_id,
            text=f"👤 <b>{curator_name}:</b>\n{message.text}",
            parse_mode="HTML"
        )
    else:
        custom_caption = f"👤 <b>{curator_name}:</b>\n{message.caption}" if message.caption else f"👤 <b>{curator_name}</b> надіслав(ла) файл"
        try:
            await message.copy_to(
                chat_id=user_id,
                caption=custom_caption,
                parse_mode="HTML"
            )
        except Exception:
            await message.bot.send_message(
                chat_id=user_id, 
                text=f"👤 <b>{curator_name}:</b>", 
                parse_mode="HTML"
            )
            await message.copy_to(chat_id=user_id)
    
    try:
        await message.react(reaction=[ReactionTypeEmoji(emoji="👍")])
    except Exception as e:
        print(f"Не вдалося поставити реакцію: {e}")

# endregion =====================================================
# region FALLBACKs
# ===============================================================

@fallback_router.message(
    F.chat.type == "private",
    F.text.in_(["❌ Скасувати", "🔙 Назад у меню", "Скасувати", "скасувати", "🚫 Скасувати введення"])
)
async def cleanup_zombie_cancel_button(message: Message):
    """Прибирає застарілу кнопку з екрана, якщо FSM стан вже None"""
    await kb.drop_reply_keyboard(message)
    await message.answer("Повертаємось у SvitloMenu:", reply_markup=kb.get_main_menu())

@fallback_router.message(F.text == "давай связь")
async def fallback_msg1(message: Message):
    await message.react(reaction=[ReactionTypeEmoji(emoji="👎")])
    await message.answer_sticker(sticker="CAACAgIAAxkBAAPTabBT4SYeNzP7oZb9oa1daBMAAcCDAAKWnQACQO5ZSeBmjQpUnOGuOgQ")

# @fallback_router.message(F.sticker)
# async def get_sticker_id(message: Message):
    # print(f"Sticker ID: {message.sticker.file_id}")
    # await message.answer(f"ID цього стікера:\n<code>{message.sticker.file_id}</code>")

@fallback_router.message(F.chat.type == "private", F.text.startswith("/"))
async def unknown_command_handler(message: Message):
    """Ловить всі команди, які не були спіймані вище (опечатки)"""
    await message.answer("🤔 Я не знаю такої команди, спробуй /menu")

@fallback_router.message(F.chat.type == "private")
async def unknown_content_handler(message: Message):
    await message.answer("Я тебе не зрозумів 🤷\nСкористайся /menu для навігації", reply_markup=ReplyKeyboardRemove())

# endregion =====================================================
# region 
# ===============================================================
