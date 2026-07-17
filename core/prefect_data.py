from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

DAYS_CHANGE = ["ПОНЕДІЛОК", "ВІВТОРОК", "СЕРЕДА", "ЧЕТВЕР", "П'ЯТНИЦЯ", "СУБОТА", "НЕДІЛЯ"]
DAYS_INTEXT = ["Понеділок", "Вівторок", "Середу", "Четвер", "П'ятницю", "Суботу", "Неділю"]
DAYS_UA = ["Понеділок", "Вівторок", "Середа", "Четвер", "П'ятниця", "Субота", "Неділя"]

PREFECTS_OLDER_SCHEDULE = {
    "Понеділок": [
        {"lesson_btn": "15:00 English for A2", "lesson_full": "English for A2", "prefect": "Kopych Anastasiia", "username": "@nastz_xq"},
        {"lesson_btn": "15:00 Career Success", "lesson_full": "Career Success Course", "prefect": "Anastasiia Ushakova", "username": "@moonincat"},
        {"lesson_btn": "16:00 Gender equality", "lesson_full": "Gender equality", "prefect": "Maria Kordunova", "username": "@kordunovamasha"},
        {"lesson_btn": "17:00 Italian", "lesson_full": "Italian", "prefect": "Angelina Bielova", "username": ""},
        {"lesson_btn": "17:00 Character Quest", "lesson_full": "The Character Quest: Unlock Your Best Self", "prefect": "Marta Domchenko", "username": "@marto4ka01"},
        {"lesson_btn": "18:00 Discussion", "lesson_full": "Discussion", "prefect": "Yeva Chelnyk", "username": "@wyevii"},
        {"lesson_btn": "19:00 Poetry", "lesson_full": "Poetry", "prefect": "Margo Krivenko", "username": "@margoshaO9"},
        {"lesson_btn": "19:00 ESOL - Discussion", "lesson_full": "ESOL - Discussion", "prefect": "Nastya Karagioz", "username": "@Nas_tya76"},
        {"lesson_btn": "20:00 ESOL - IELTS Prep", "lesson_full": "ESOL - IELTS Preparation", "prefect": "Christie kravchenko", "username": ""},
        {"lesson_btn": "20:00 Excel Topics", "lesson_full": "Excel Topics", "prefect": "Anna", "username": "@anotirix"}
    ],
    "Вівторок": [
        {"lesson_btn": "15:00 AI Basics", "lesson_full": "AI Basics", "prefect": "Pavlo Zabrodotskyi", "username": "@passshokk"},
        {"lesson_btn": "16:00 Art and Maths", "lesson_full": "Art and Maths", "prefect": "Oleksandr Teliha", "username": "@telihaol"},
        {"lesson_btn": "16:00 Physics", "lesson_full": "Physics", "prefect": "Karolina Lytvynenko", "username": "@crims9nn"},
        {"lesson_btn": "17:00 To Kill a Mockingbird", "lesson_full": "To Kill a Mockingbird Bird", "prefect": "Milana Virkovska", "username": "@miqcass"},
        {"lesson_btn": "18:00 UN Model", "lesson_full": "UN Model", "prefect": "𝓚𝓲𝓻𝓪 𝓑𝓸𝔂𝓪𝓻𝓬𝓱𝓾𝓴𝓸𝓿𝓪", "username": "@Werewolf_Fenrir"},
        {"lesson_btn": "18:00 Book club", "lesson_full": "Book club", "prefect": "Daria Matsiura", "username": "@rotentar"},
        {"lesson_btn": "19:00 Reading Buddy", "lesson_full": "Reading Buddy", "prefect": "Galina Chakmakly", "username": "@galina_chakmakly"},
        {"lesson_btn": "19:00 ESOL - Grammar", "lesson_full": "ESOL - Grammar", "prefect": "Marharyta Bartnychuk", "username": "@mbartny"},
        {"lesson_btn": "20:00 Svitlo News Club", "lesson_full": "Svitlo News Club", "prefect": "Arina Bilan", "username": "@arina_rianna21"},
        {"lesson_btn": "20:00 Maths", "lesson_full": "Maths", "prefect": "Antonia Rudenko", "username": "@brssvch"}
    ],
    "Середа": [
        {"lesson_btn": "15:00 Creative Writing", "lesson_full": "Creative Writing - Through My Eyes", "prefect": "Anna Kormysheva", "username": "@av_lumiere"},
        {"lesson_btn": "16:00 Spanish Speaking", "lesson_full": "Spanish Speaking Club", "prefect": "Anastasiia Samsonenko", "username": "@aewwasa"},
        {"lesson_btn": "16:00 Debating", "lesson_full": "Debating", "prefect": "Diana Tarasevska", "username": "@im_diana_smm"},
        {"lesson_btn": "17:00 Discussion Forum", "lesson_full": "Discussion Forum - current events, social issues", "prefect": "Nadya Vorova", "username": "@nadyaaa_10"},
        {"lesson_btn": "17:00 Career Kickstart", "lesson_full": "Career Kickstart Beginners", "prefect": "ALEVTYNA BULATOVA", "username": "@alyaaewww"},
        {"lesson_btn": "18:00 Film Studies", "lesson_full": "Film Studies: holiday movies", "prefect": "Galina Chakmakly", "username": "@galina_chakmakly"},
        {"lesson_btn": "19:00 U.S. History", "lesson_full": "Case Studies in U.S. History: French & Indian War", "prefect": "Chemiorkin Matviy", "username": "@PavloZibrowv"},
        {"lesson_btn": "20:00 Making Money", "lesson_full": "Making and Keeping Money", "prefect": "Daria Romanii", "username": "@deluvella"},
        {"lesson_btn": "20:00 Making Sense of AI", "lesson_full": "Making Sense of AI", "prefect": "Marta Vasylytsia", "username": "@M8_aR1"}
    ],
    "Четвер": [
        {"lesson_btn": "15:00 Biology", "lesson_full": "Biology", "prefect": "Olena Pelek", "username": "@Olenush1"},
        {"lesson_btn": "16:00 Speakers Corner", "lesson_full": "Speakers Corner", "prefect": "Varvara Chub", "username": "@chvarvara"},
        {"lesson_btn": "17:00 Social Media", "lesson_full": "Social Media: Use and Abuse of Social Media", "prefect": "Ulya Shapoval", "username": "@trwixj"},
        {"lesson_btn": "18:00 European Culture", "lesson_full": "European Culture from 1600", "prefect": "Sofia Romanchuk", "username": "@Darknesarrives"},
        {"lesson_btn": "19:00 Human Geography", "lesson_full": "Human Geography", "prefect": "Kateryna Sukhanova", "username": "@kentawtix"},
        {"lesson_btn": "20:00 Engeneering Topics", "lesson_full": "Engeneering Topics", "prefect": "Anastasia Herasymych", "username": "@nast_he"},
        {"lesson_btn": "20:00 Government", "lesson_full": "Government: World War II alliances", "prefect": "Anastasia Bilak", "username": "@s_ellacy"},
        {"lesson_btn": "21:00 Session", "lesson_full": "Session", "prefect": "Anastasia Krasnikova", "username": "@AnastaasiaKV"}
    ],
    "П'ятниця": [
        {"lesson_btn": "14:00 Business English", "lesson_full": "Business English", "prefect": "Viktoriia Khoruzha", "username": "@Khoruzhav"},
        {"lesson_btn": "15:00 Adventure scenarios", "lesson_full": "Adventure scenarios: What would you do?", "prefect": "Maria Lialko", "username": "@mmewcury"},
        {"lesson_btn": "15:00 Physical Geography", "lesson_full": "Physical Geography", "prefect": "Vladyslava Snigur", "username": "@ugvhtddfff"},
        {"lesson_btn": "16:00 Peaceful Warrior", "lesson_full": "Path of the Peaceful Warrior", "prefect": "Valeriya Popova", "username": "@h2442sz"},
        {"lesson_btn": "17:00 Circle time", "lesson_full": "Circle time", "prefect": "Mariia Ivantsiva", "username": "@ivantsivamariia"},
        {"lesson_btn": "17:30 Travel and Tourism", "lesson_full": "Travel and Tourism", "prefect": "Elizabeth Holokolosova", "username": "@history_explorer"},
        {"lesson_btn": "18:00 Social Hour", "lesson_full": "Social Hour: informal dicussion", "prefect": "Alina Shevchuk", "username": "@n_a_m_e_e"},
        {"lesson_btn": "19:00 American Studies", "lesson_full": "American Studies: American football", "prefect": "Vlada Khranovska", "username": "@Sunshiyne_0"},
        {"lesson_btn": "20:00 Session", "lesson_full": "Session", "prefect": "Dana Nanivska", "username": "@Nanik_Dana"},
        {"lesson_btn": "21:00 Mafia Club", "lesson_full": "Mafia Club", "prefect": "Gordiy", "username": "@LeW1k27"}
    ],
    "Субота": [
        {"lesson_btn": "10:00 Chemistry", "lesson_full": "Chemistry", "prefect": "Anastasiia Lanko", "username": "@femme1fatale3"},
        {"lesson_btn": "10:00 Hatha yoga", "lesson_full": "Hatha yoga", "prefect": "Polina Pyshniuk", "username": "@Spid3ySleeps"},
        {"lesson_btn": "11:00 Leadership Skills", "lesson_full": "Leadership Skills", "prefect": "Anhelina Yakymenko", "username": "@linaxxass"},
        {"lesson_btn": "12:00 Leadership Skills", "lesson_full": "Leadership Skills/ small group", "prefect": "Yulianna Dudla", "username": "@yulia_dudla"},
        {"lesson_btn": "13:00 Drama class", "lesson_full": "Drama class", "prefect": "Yurii Dykyi", "username": "@YuriiWild"},
        {"lesson_btn": "17:00 Cryptocurrency", "lesson_full": "Cryptocurrency", "prefect": "Tymur Shakun", "username": "@Tymur_Shakun"},
        {"lesson_btn": "18:00 Financial Literacy", "lesson_full": "Financial Literacy", "prefect": "Oleksandra Dorozh", "username": "@andra_dor"},
        {"lesson_btn": "19:00 Game Night", "lesson_full": "Game Night with Houses", "prefect": "Oleksandra Laskavtseva", "username": "@lasalexan"}
    ],
    "Неділя": [
        {"lesson_btn": "12:00 Interm. English", "lesson_full": "Intermediate Conversational English", "prefect": "Anastasia Marchuk", "username": "@Langgeng_av"},
        {"lesson_btn": "18:00 Meditation", "lesson_full": "Meditation", "prefect": "Dasha Pashchenko", "username": "@Gads_haha"},
        {"lesson_btn": "19:00 Sustainability", "lesson_full": "Sustainability Topics", "prefect": "Evelina Sliusar", "username": "@slsevelina"}
    ]
}

PREFECTS_YOUNGER_SCHEDULE = {
    "Понеділок": [
        {"lesson_btn": "15:00 Famous people", "lesson_full": "Some famous (and not so famous) interesting people", "prefect": "Anna Denysiuk", "username": "@muliksw"},
        {"lesson_btn": "15:00 Intro to Biology", "lesson_full": "Intro to Biology", "prefect": "Dima Kharchenko", "username": "@Dima_kij"},
        {"lesson_btn": "16:00 English for A2", "lesson_full": "English for A2", "prefect": "Shved Bozhena", "username": "@flasixs"},
        {"lesson_btn": "17:00 English A2 Gr 1", "lesson_full": "English A2 Group 1", "prefect": "", "username": "@LeW1k27"},
        {"lesson_btn": "18:00 English A2 Gr 2", "lesson_full": "English A2 Group 2", "prefect": "", "username": "@LeW1k27"},
        {"lesson_btn": "19:00 English B1+ Gr 1", "lesson_full": "English B1+ Group 1", "prefect": "", "username": "@LeW1k27"},
        {"lesson_btn": "19:00 English A1 level", "lesson_full": "English A1 level", "prefect": "Tetiana Kornienko", "username": "@Tanya_lol123"},
        {"lesson_btn": "20:00 Drawing class", "lesson_full": "Drawing class", "prefect": "Daryna Kryvenko", "username": "@dirmixx"},
        {"lesson_btn": "20:00 AI Literacy", "lesson_full": "AI Literacy", "prefect": "Shved Bozhena", "username": "@flasixs"}
    ],
    "Вівторок": [
        {"lesson_btn": "15:00 English A2+", "lesson_full": "English A2+", "prefect": "", "username": ""},
        {"lesson_btn": "16:00 Art and Maths", "lesson_full": "Art and Maths", "prefect": "older student", "username": "older student"},
        {"lesson_btn": "16:45 English Elem. A1", "lesson_full": "English Elementary A1", "prefect": "Kateryna Liubchenko", "username": "@bratyscheva"},
        {"lesson_btn": "17:00 English A2-B1", "lesson_full": "English A2-B1 level", "prefect": "Melania Dorozhkina", "username": "@Seariys"},
        {"lesson_btn": "20:00 Movie Club", "lesson_full": "Movie Club", "prefect": "Daria Dorozhkina, Kira Volchanova", "username": ""},
        {"lesson_btn": "21:00 Music", "lesson_full": "Music", "prefect": "", "username": ""}
    ],
    "Середа": [
        {"lesson_btn": "14:00 Draw together", "lesson_full": "Draw together", "prefect": "Sasha Vasylenko & the crew", "username": ""},
        {"lesson_btn": "14:00 Creative Writing", "lesson_full": "Creative Writing - Through My Eyes", "prefect": "", "username": ""},
        {"lesson_btn": "15:00 Debating", "lesson_full": "Debating", "prefect": "Polina Lvova", "username": "@Ponchikuuuu"},
        {"lesson_btn": "15:00 English A1+", "lesson_full": "English A1+", "prefect": "", "username": ""},
        {"lesson_btn": "16:00 Story time Gr 1", "lesson_full": "Story time Group 1", "prefect": "Alisa Mikhno", "username": "@fell_for_neymar"},
        {"lesson_btn": "17:00 Story time Gr 2", "lesson_full": "Story time Group 2", "prefect": "Oleksandra Poliakova", "username": "@cheriive_26"},
        {"lesson_btn": "17:00 English B1 Gr 1", "lesson_full": "English B1 Group 1", "prefect": "", "username": "@LeW1k27"},
        {"lesson_btn": "18:00 English B1+ Gr 2", "lesson_full": "English B1+ Group 2", "prefect": "", "username": ""},
        {"lesson_btn": "19:00 English B1 Gr 2", "lesson_full": "English B1 Group 2", "prefect": "", "username": ""},
        {"lesson_btn": "19:15 Giglets' Story time", "lesson_full": "Giglets' Story time", "prefect": "Alisa Sokolovska", "username": "@alichilli"},
        {"lesson_btn": "20:00 Geography", "lesson_full": "Geography - Countries of the world", "prefect": "Daria Dorozhkina", "username": "@dashwws"}
    ],
    "Четвер": [
        {"lesson_btn": "14:00 Story reading", "lesson_full": "Story reading", "prefect": "Daria Dorozhkina", "username": "@dashwws"},
        {"lesson_btn": "14:30 Exploration of Art", "lesson_full": "Exploration of Art From Around the World", "prefect": "Kira Volchanova", "username": "@kiritiki_v"},
        {"lesson_btn": "16:00 Canada and English", "lesson_full": "Canada and English", "prefect": "Anna Denysiuk", "username": "@muliksw"},
        {"lesson_btn": "17:00 Get-to-know-you", "lesson_full": "Get-to-know-you session with Daria Shynkaruk, your new psychologist", "prefect": "Daria Shynkaruk", "username": ""},
        {"lesson_btn": "18:00 Reading legends", "lesson_full": "Reading legends together", "prefect": "Elizabeth Holokolosova", "username": ""},
        {"lesson_btn": "18:00 Victorian Britain", "lesson_full": "Victorian Britain", "prefect": "Lidia Lebedieva", "username": "@Harry_Potter_fan_forever"},
        {"lesson_btn": "19:00 Literature Iron Man", "lesson_full": "Literature - Iron Man", "prefect": "Kira Volchanova", "username": "@kiritiki_v"},
        {"lesson_btn": "19:00 Summer Camp Ess.", "lesson_full": "Summer Camp Essentials: What to Expect and How to Prepare", "prefect": "Council Students", "username": ""},
        {"lesson_btn": "20:00 Decode songs", "lesson_full": "Decode songs - A1-A2", "prefect": "Yaroslava Rohovyk", "username": "@royarvi"}
    ],
    "П'ятниця": [
        {"lesson_btn": "14:00 Ivana Kupala Quiz", "lesson_full": "Ivana Kupala Quiz", "prefect": "Anna Bahmutova", "username": ""},
        {"lesson_btn": "15:00 Adv. scenarios", "lesson_full": "Adventure scenarios: What would you do?", "prefect": "", "username": ""},
        {"lesson_btn": "16:00 Would you rather", "lesson_full": "Would you rather, Orli Edition", "prefect": "Daniel Hrebenuk", "username": "@danilloves_football"},
        {"lesson_btn": "16:00 Circle time", "lesson_full": "Circle time", "prefect": "Miroslava Rybalchenko", "username": "@mira_cor"},
        {"lesson_btn": "17:00 English in Nigeria", "lesson_full": "English through the Nigeria", "prefect": "Kira Volchanova", "username": "@kiritiki_v"},
        {"lesson_btn": "18:00 Speaking English", "lesson_full": "Speaking English with Confidence", "prefect": "Zhanna Kobyliak", "username": "@wayllim"},
        {"lesson_btn": "19:00 English A1 level", "lesson_full": "English A1 level", "prefect": "Victoria Dotsenko", "username": "@wizzxq"},
        {"lesson_btn": "20:00 The Classics Club", "lesson_full": "The Classics Club: The end of the Roman Republic", "prefect": "Miroslava Rybalchenko", "username": "@mira_cor"},
        {"lesson_btn": "21:00 Mafia Club", "lesson_full": "Mafia Club", "prefect": "Gordiy Zakusylo/Solomiya Surmach", "username": ""}
    ],
    "Субота": [
        {"lesson_btn": "11:00 Harmony in Mind", "lesson_full": "Harmony in Mind & Matter: M²S", "prefect": "Dima Kharchenko", "username": "@Dima_kij"},
        {"lesson_btn": "12:00 Drama class", "lesson_full": "Drama class", "prefect": "Polina Azhischeva", "username": "@pollyweq_6"},
        {"lesson_btn": "16:00 Investment club", "lesson_full": "Investment club", "prefect": "Oleksii Kolinko", "username": "@Lexus_Guy"},
        {"lesson_btn": "17:00 Coding in Python", "lesson_full": "Coding in Python", "prefect": "Daria Dorozhkina", "username": "@dashwws"},
        {"lesson_btn": "18:00 Spanish Beginner", "lesson_full": "Spanish Beginner, group 1", "prefect": "Kira Volchanova", "username": "@kiritiki_v"},
        {"lesson_btn": "19:00 Game Night", "lesson_full": "Game Night with Houses", "prefect": "Gordiy Zakusylo", "username": ""}
    ],
    "Неділя": [
        {"lesson_btn": "13:00 World Cup", "lesson_full": "World Cup", "prefect": "Matvii Radkevych", "username": "@wegesed"},
        {"lesson_btn": "14:00 Summer Quiz", "lesson_full": "Summer Quiz", "prefect": "Lisa", "username": ""},
        {"lesson_btn": "15:00 Korean Club", "lesson_full": "Korean Club", "prefect": "Roza Mursaliieva", "username": "@skz_felix_stay"},
        {"lesson_btn": "16:00 Spanish Beginner", "lesson_full": "Spanish Beginner, group 2", "prefect": "Misha Zabrodotskyi", "username": "@misssh_ok"},
        {"lesson_btn": "17:00 Yoga class", "lesson_full": "Yoga class", "prefect": "Lidia Lebedieva", "username": "@Harry_Potter_fan_forever"},
        {"lesson_btn": "20:00 Official Distrib.", "lesson_full": "Official Distribution of 5th term Newbies", "prefect": "Houses of Svitlo/ Sasha Vasylenko", "username": ""}
    ]
}

SCHEDULE_MAPPING = {
    "older": {"schedule": PREFECTS_OLDER_SCHEDULE, "cb_data": "oldpref_day", "select_pr": "oldpref_sel"},
    "younger": {"schedule": PREFECTS_YOUNGER_SCHEDULE, "cb_data": "ypref_day", "select_pr": "ypref_sel"}
}

def get_prefects_day_keyboard(day_index: int, group) -> InlineKeyboardMarkup:
    """
    Dispays prefects schedule buttons
    """
    builder = InlineKeyboardBuilder()

    day_name = DAYS_UA[day_index]
    target_group = SCHEDULE_MAPPING[group]["schedule"]
    lessons = target_group.get(day_name, [])

    cb_pref_day = SCHEDULE_MAPPING[group]["cb_data"]
    pref_sel = SCHEDULE_MAPPING[group]["select_pr"]

    prev_day = (day_index - 1) % 7
    next_day = (day_index + 1) % 7
    builder.row(
        InlineKeyboardButton(text=f"◀️ {DAYS_CHANGE[prev_day]}", callback_data=f"{cb_pref_day}:{prev_day}"),
        InlineKeyboardButton(text=f"{DAYS_CHANGE[next_day]} ▶️", callback_data=f"{cb_pref_day}:{next_day}")
    )

    for lesson_idx, data in enumerate(lessons):
        btn_text = data['lesson_btn']
        cb_data = f"{pref_sel}:{day_index}:{lesson_idx}"
        builder.button(text=btn_text, callback_data=cb_data)
    
    builder.adjust(2, *([1] * len(lessons)))
    
    builder.row(InlineKeyboardButton(text="🔙 Назад у меню", callback_data="main_menu"))
    
    return builder.as_markup()