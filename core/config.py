GROUPS_MAPPING = {
    "older": -1001695260775,
    "younger": -1001584085066
}

HOUSE_CHATS = {
    "Caledonia": -1002434733152,
    "Hibernia": -1002451381823,
    "Cambria": -1002432858864,
    "Albion": -1002378397420,
}

CURATOR_GROUP_ID = -1004393635348
ADMIN_GROUP_ID = -1003951532483
# TESTER_IDS зберігається в Firestore: Config/bot_settings.tester_ids (core.database.get_tester_ids/add_tester_id/remove_tester_id)
OWNER_ID = 1125108435  # єдиний, кому доступна /testers

MAIN_CURATOR_USERNAME = "@passshokk"

# ----------------------------------

EMAIL_REGEX = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
PHONE_REGEX = r'^\+[1-9]\d{7,14}$'
ENG_NAME_REGEX = r'^[A-Za-z\s\-\']{2,20}$'
# Українська кирилиця (без ъ/ы/э, які належать лише російському алфавіту) для полів на кшталт міста, країни, ПІБ батьків
UKR_REGEX = r"^[А-Ща-щЬьЮюЯяҐґЄєІіЇї'’\-\s]{2,50}$"

# Найпопулярніші поштові домени серед українських заявників — база для типо-перевірки email (core.utils.suggest_email_domain_fix)
TRUSTED_EMAIL_DOMAINS = {
    "gmail.com", "ukr.net", "i.ua", "meta.ua", "outlook.com",
    "hotmail.com", "yahoo.com", "icloud.com", "protonmail.com", "gmx.com", "live.com",
}

ROLE_MAP = {
    "itt": "💻 ITT member",
    "scl": "🏛️ Student Council member",
    "buddy": "🤝 Buddy",
    "prefect": "📝 Prefect",
    "student": "🎓 Student",
    "boss": "🛐 о Паша мой павєлітєль",
}

CATEGORY_THREADS = {
    "Технічні баги": 194, # зробити ключ категорії списком (номер, відповідальний куратор) 
    "Освітній процес": 196,
    "Організаційні питання": 198
}
