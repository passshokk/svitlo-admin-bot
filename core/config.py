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
ADMIN_GROUP_ID = -5437292784
# DEV_IDS перенесено в Firestore: Config/bot_settings.dev_ids (core.database.get_dev_ids/add_dev_id/remove_dev_id)

MAIN_CURATOR_USERNAME = "@passshokk"

# ----------------------------------

EMAIL_REGEX = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
PHONE_REGEX = r'^\+[1-9]\d{7,14}$'
ENG_NAME_REGEX = r'^[A-Za-z\s\-\']{2,20}$'

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
