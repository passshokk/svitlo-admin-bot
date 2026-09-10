GROUPS_MAPPING = {
    "older": -1001695260775,
    "younger": -1001584085066
}

HOUSE_CHATS = {
    "Caledonia": -3904151695,
    "Hibernia": -4498108891,
    "Cambria": -3853175079,
    "Albion": -4459512165,
}

CURATOR_GROUP_ID = -1004393635348
ADMIN_GROUP_ID = -1003951532483
# Тестувальники зберігаються в Firestore: Config/bot_settings.testers (core.database.get_tester_ids/get_testers/add_tester_id/remove_tester_id)
OWNER_ID = 1125108435  # єдиний, кому доступна /testers

MAIN_CURATOR_USERNAME = "@martamalynowska"

# ----------------------------------

EMAIL_REGEX = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
ENG_NAME_REGEX = r'^[A-Za-z\s\-\']{2,20}$'
# Українська кирилиця (без ъ/ы/э, які належать лише російському алфавіту) для полів на кшталт міста, країни, ПІБ батьків
UKR_REGEX = r"^[А-Ща-щЬьЮюЯяҐґЄєІіЇї'’\-\s]{2,50}$"

# Найпопулярніші поштові домени серед українських заявників — база для типо-перевірки email (core.utils.suggest_email_domain_fix)
TRUSTED_EMAIL_DOMAINS = {
    "gmail.com", "ukr.net", "i.ua", "meta.ua", "outlook.com",
    "hotmail.com", "yahoo.com", "icloud.com", "protonmail.com", "gmx.com", "live.com",
}

ROLE_MAP = {
    "itt": "💻 IT team",
    "scl": "🏛️ Student Council Member",
    "buddy": "🤝 Buddy",
    "prefect": "📝 Prefect",
    "student": "🎓 Student"
}

# LEGACY: раніше всі тікети категорії летіли в один спільний thread. Тепер кожен тікет
# отримує власну гілку (створюється динамічно, id лежить у SupportCentreTickets/{id}.thread_id).
# Мапа лишається лише як fallback для тікетів, відкритих ДО цього переходу.
CATEGORY_THREADS = {
    "Технічні баги": 194,
    "Освітній процес": 196,
    "Організаційні питання": 198,
    "Реєстрація": 282,
}

# Скільки чекати після закриття тікета, перш ніж видалити його гілку в CURATOR_GROUP_ID
# (даємо кураторам хвилину-дві на "останній погляд", перш ніж вона зникне назавжди)
TICKET_THREAD_DELETE_DELAY_SECONDS = 120

# Кольори іконок гілок підтримки за категорією (одне з 6 фіксованих значень Telegram Bot API)
CATEGORY_TOPIC_COLORS = {
    "Технічні баги": 0xFB6F5F,      # червоний
    "Освітній процес": 0x6FB9F0,    # синій
    "Організаційні питання": 0xFFD67E,  # жовтий
    "Реєстрація": 0x8EEE98,         # зелений
}
