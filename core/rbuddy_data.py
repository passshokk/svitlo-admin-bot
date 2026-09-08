from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

DAYS_CHANGE = ["ПОНЕДІЛОК", "ВІВТОРОК", "СЕРЕДА", "ЧЕТВЕР", "П'ЯТНИЦЯ", "СУБОТА", "НЕДІЛЯ"]
DAYS_INTEXT = ["Понеділок", "Вівторок", "Середу", "Четвер", "П'ятницю", "Суботу", "Неділю"]
DAYS_UA = ["Понеділок", "Вівторок", "Середа", "Четвер", "П'ятниця", "Субота", "Неділя"]

SCHEDULE = {
    "Понеділок": [
        {"time": "17:30", "name": "Mariia Chakhovska", "url": "https://t.me/+MSWwR6mS_NU2MWRi"},
        {"time": "18:00", "name": "Yelyzaveta Hilevych", "url": "https://t.me/+pcLTHz5J-Yk2ZmNi"},
        {"time": "18:30", "name": "Polina Kuzmenko", "url": "https://t.me/+-bE_ZIECYYg0ZmEy"},
        {"time": "18:30", "name": "Stacy Kiurkchi/Milana Virkovska", "url": "https://t.me/+MGqGDTEdW-EzYTEy"},
        {"time": "19:00", "name": "Anna Kormysheva", "url": "https://t.me/+I_bPfhPv-XZhMDhi"}
    ],
    "Вівторок": [
        {"time": "18:00", "name": "Nastya Karagioz", "url": "https://t.me/+kRFdrHKW5cs4NDMy"},
        {"time": "18:30", "name": "Anna Bahmutova", "url": "https://t.me/+Mo2wKrkYeKZhYzky"},
        {"time": "18:30", "name": "Marta Domchenko", "url": "https://t.me/+vtCjHY0SA0JlM2Ey"},
        {"time": "19:00", "name": "Sasha Vasylenko", "url": "https://t.me/+-IlF-kP5fY1lZjQy"},
        {"time": "19:00", "name": "Lisa Chechel", "url": None},
        {"time": "19:00", "name": "Albina Peresada/Sofia Romanchuk", "url": None},
        {"time": "19:30", "name": "Alina Shevchuk", "url": "https://t.me/+P3TEo3HtGCBhYWVi"},
        {"time": "19:30", "name": "Yurii Dykyi", "url": "https://t.me/+sUfUvC-Wez03YmRi"},
        {"time": "19:30", "name": "Anastasia Bilak", "url": "https://t.me/+KdlsTwxCGkI0YzAy"},
        {"time": "20:00", "name": "Diana Yefimushkina", "url": "https://t.me/+uhcwckXckeAzZWUy"}
    ],
    "Середа": [
        {"time": "18:00", "name": "Anastasia Krasnikova", "url": "https://t.me/+lIKyYKXnatFhMDY6"},
        {"time": "18:00", "name": "Vlada Khranovska", "url": "https://t.me/+1X0JRTgjrLUzZWFi"},
        {"time": "18:30", "name": "Christie Kravchenko", "url": None},
        {"time": "18:30", "name": "Marharyta Bartnychuk", "url": "https://t.me/+WrvvX4amfjA5YmNi"},
        {"time": "19:00", "name": "Varvara Chub", "url": "https://t.me/+7t3tTNj1ENxhOGMy"},
        {"time": "19:30", "name": "Oleksandra Solovei", "url": "https://t.me/+-Wstn1sXHzMwZmRi"},
        {"time": "19:30", "name": "Anastasiia Marchuk", "url": "https://t.me/+XmDjnWqzYh04NTUy"}
    ],
    "Четвер": [
        {"time": "12:00", "name": "Varvara Chub", "url": "https://t.me/+7t3tTNj1ENxhOGMy"},
        {"time": "19:00", "name": "Dori Matsiura", "url": "https://t.me/+Bj-_ItcjqkE4MzU6"},
        {"time": "19:00", "name": "Valeriya Popova", "url": "https://t.me/+6uvdzUfFsuYzYmNi"},
        {"time": "19:30", "name": "Mariam Anabtavi", "url": "https://t.me/+7BsUyb11hPc2Yjky"},
        {"time": "20:00", "name": "Oleksandra Laskavtseva", "url": "https://t.me/+6McmLwdqCY9mM2My"},
        {"time": "20:00", "name": "Galina Cakmakly", "url": "https://t.me/readingpeppapig"},
        {"time": "20:30", "name": "Elizabeth Holokolosova", "url": None},
        {"time": "20:30", "name": "Anhelina Bielova", "url": "https://t.me/+2BO4bHy-D3Q2YTZi"}
    ],
    "П'ятниця": [
        {"time": "17:00", "name": "Diana Tarasevska", "url": "https://t.me/+7-4SBemixMY0ZDNi"},
        {"time": "17:00", "name": "Solomiya Surmach/Viktoriia Serhiichuk", "url": "https://t.me/+354Jr_X-cJ4xMTZi"},
        {"time": "17:30", "name": "Vladyslava Snigur", "url": "https://t.me/+ADfb8jT6q0JmMjAy"},
        {"time": "17:30", "name": "Anastasiia Samsonenko", "url": "https://t.me/+TmHbEaxfjyc3OTli"},
        {"time": "18:00", "name": "Daria Vilk", "url": "https://t.me/+Fc2IikYAYrM4NjI6"},
        {"time": "19:30", "name": "Oleksandr Teliha", "url": "https://t.me/+7Jobsp7aNLRjNjky"},
        {"time": "19:30", "name": "Evelina Sliusar", "url": "https://t.me/+e1qcGYG8Qog2Nzky"}
    ],
    "Субота": [
        {"time": "13:00", "name": "Oleksandra Dorozh", "url": "https://t.me/+HQOmScOimi41MDQy"},
        {"time": "13:30", "name": "Antonia Rudenko", "url": "https://t.me/+q4PS_Wda-FxlYmRi"},
        {"time": "14:00", "name": "Dasha Pashchenko", "url": "https://t.me/+FKXWslasmx5lNjMy"},
        {"time": "14:00", "name": "Sofia Perederiy", "url": "https://t.me/+GCHktDq5QBhkZDAy"}
    ],
    "Неділя": [
        {"time": "11:30", "name": "Anastasiia Ushakova", "url": "https://t.me/+OjBfvFxt0lg2NzA6"},
        {"time": "12:00", "name": "Lara Onopriienko", "url": "https://t.me/+QoOvdaPtIWIzMTQy"},
        {"time": "12:30", "name": "Ira Kasylova", "url": "https://t.me/+QWImXNoxxCpmOWUy"},
        {"time": "13:00", "name": "Kira Boyarchukova", "url": None},
        {"time": "13:00", "name": "Albina Peresada/Sofia Romanchuk", "url": "https://t.me/+7cposz47Zok5YjAy"},
        {"time": "13:00", "name": "Dana Nanivska/Daria Romanii", "url": "https://t.me/+1u0eelIeVl5hYTli"}
    ]
}

def get_rbuddy_day_keyboard(day_index: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    day_name = DAYS_UA[day_index]
    buddies = SCHEDULE.get(day_name, [])

    prev_day = (day_index - 1) % 7
    next_day = (day_index + 1) % 7
    builder.row(
        InlineKeyboardButton(text=f"◀️ {DAYS_CHANGE[prev_day]}", callback_data=f"rb_day:{prev_day}"),
        InlineKeyboardButton(text=f"{DAYS_CHANGE[next_day]} ▶️", callback_data=f"rb_day:{next_day}")
    )

    for buddy_id, buddy in enumerate(buddies):
        btn_text = f"{buddy['time']} {buddy['name']}"
        url = buddy.get('url')
        
        if url and url.startswith("http"):
            builder.button(text=btn_text, url=url)
        else:
            # Кнопка-заглушка для тих, у кого немає посилання або воно на платформі
            status = "platform" if url == "platform" else "empty"
            builder.button(text=btn_text, callback_data=f"no_url:{status}")

    builder.adjust(2, *([1] * len(buddies)))
    builder.row(InlineKeyboardButton(text="🔙 Назад у меню", callback_data="main_menu"))
    
    return builder.as_markup()