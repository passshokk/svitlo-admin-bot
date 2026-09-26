# core/academic_calendar.py
"""Навчальний календар: семестри, канікули, Shopping Week, Induction Week.

Навіщо він узагалі. Дати школи досі жили ВІЛЬНИМ ТЕКСТОМ у
`Config/bot_settings` (`termStartDate`, `inductionStartDate`) і підставлялись
у повідомлення без парсингу. Копій було дві, і вони вже розійшлись:
бот тримав "Понеділок, 14 вересня 2026 року", панель — "14 вересня".
Машинних дат не було ніде, тож жодна аналітика не могла спитати
"а це взагалі навчальний тиждень чи канікули".

Чому файл зветься academic_calendar, а не calendar: `calendar` — модуль
стандартної бібліотеки, і однойменний файл у пакеті плутає читача навіть
там, де технічно не конфліктує.

ДЗЕРКАЛЬНИЙ модуль: така сама копія лежить у панелі
(`svitlo_admin_panel/core/academic_calendar.py`). Той самий підхід, що вже
застосований для `_log_stage_event` — одна логіка, дві копії, бо спільного
пакета між проєктами немає. Міняти треба ОБИДВІ. Єдина відмінність між
копіями — звідки береться клієнт Firestore (`core.database` тут,
`core.firestore_client` у панелі).

Структура документа `Config/academic_calendar` (один на навчальний рік,
формат із 26.09.2026 — семестр як широкі межі, періоди всередині):

    {
      "year": "2026-27",
      "timezone": "Europe/Kyiv",
      "semesters": [
        {"code": "26-27_01",
         "from": <14.09.2026 00:00>, "to": <25.10.2026 23:59:59>,   # shopping -> кінець term
         "periods": [
           {"kind": "admission", "from": ..., "to": ...},
           {"kind": "induction", ...}, {"kind": "shopping", ...}, {"kind": "term", ...},
         ]},
        ...
      ],
      "breaks": [{"kind": "summer", "from": ..., "to": ..., "semester": "27-28_01"}],
      "analytics": {"velocityBaselineFrom": "...", "trimmedMeanPercent": 5}
    }

Межі семестру (`from`/`to`) — від початку Shopping Week до останнього дня
навчання, як їх пише школа. Періоди семестру можуть виходити за ці межі:
набір (`admission`) іде ДО них, різдвяний спецтиждень — ПІСЛЯ, і обидва все
одно належать цьому семестру. Разом із `breaks` періоди покривають рік
СУЦІЛЬНО, без дірок і перекриттів.

Старий плаский формат (`segments` зі `semester` на кожному, тип `holidays`
замість `admission`) досі читається: поки бот не оновлено, документ несе
обидва, і новий парсер бере `semesters`. Код нижче працює з пласким списком
сегментів у будь-якому разі — формат документа міняє лише розбір.

Періоди набору несуть код того семестру, який вони ВІДКРИВАЮТЬ.

Це не технічна умовність: набір заявок на семестр стартує з першого дня
канікул перед ним, тож "семестр" як вікно аналітики = "коли прийшла ця
когорта". Прив'язка канікул уперед робить межу вікна тією самою межею,
на якій починає надходити когорта.

Побічний ефект, заради якого код лежить у ДАНИХ, а не у виведенні: хвостові
канікули року (19.07-31.08.2027) несуть код `27-28_01` — семестру, решта
якого житиме вже в документі наступного року. Вивести це з сусідніх
сегментів було б неможливо.
"""
import asyncio
import logging
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from core.database import db

KYIV = ZoneInfo("Europe/Kyiv")

CALENDAR_DOC = ("Config", "academic_calendar")

# Типи сегментів. `admission` — міжсеместрова пауза, у яку відкривається
# набір на наступний семестр (до 26.09.2026 цей тип звався `holidays`, і
# старі документи з ним досі читаються — див. _KIND_ALIASES).
#
# `summer` окремо від `admission` навмисно. Міжсеместрова пауза — ВСЕРЕДИНІ
# року, з набором. Літні канікули — кінець року: набору в них немає, і
# плутати їх у підписах і в next_intake_start() означало б обіцяти набір
# там, де його не буде. Довжина пауз НЕ стала (6 днів, тиждень, два тижні,
# 44 дні влітку), тож жодного "рівно тиждень" у коді бути не може.
KIND_ADMISSION = "admission"
KIND_HOLIDAYS = KIND_ADMISSION  # стара назва, лишена для імпортів
KIND_SUMMER = "summer"
KIND_INDUCTION = "induction"
KIND_SHOPPING = "shopping"
KIND_TERM = "term"
KIND_CHRISTMAS = "christmas"
SEGMENT_KINDS = (KIND_ADMISSION, KIND_SUMMER, KIND_INDUCTION, KIND_SHOPPING,
                 KIND_TERM, KIND_CHRISTMAS)
# Назви типів зі старих документів -> теперішні.
_KIND_ALIASES = {"holidays": KIND_ADMISSION}

# Канікули в широкому сенсі — "уроків немає". Саме це питання ставить графік
# трендів, коли малює сіру смугу під просадкою.
BREAK_KINDS = (KIND_ADMISSION, KIND_SUMMER)

# Місяці в родовому відмінку — саме він потрібен у "7 вересня".
# Своя таблиця, а не locale: на Cloud Run українська локаль не встановлена,
# і strftime("%B") віддав би англійську мовчки, без помилки.
_UK_MONTHS_GEN = (
    "січня", "лютого", "березня", "квітня", "травня", "червня",
    "липня", "серпня", "вересня", "жовтня", "листопада", "грудня",
)
_UK_WEEKDAYS = (
    "понеділок", "вівторок", "середа", "четвер", "п'ятниця", "субота", "неділя",
)
_EN_MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)
_EN_WEEKDAYS = (
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
)


def _as_date(value) -> date | None:
    """Firestore Timestamp, date, або ISO-рядок -> date. Все інше -> None.

    Сегменти зберігаються справжніми датами (Timestamp), а не рядками —
    у Rowy це дає нормальний date picker замість вільного тексту, де легко
    налажати з форматом. Пишемо їх опівдні UTC (той самий прийом, що вже
    є в боті для birthDate: `bot/reg_funnel.py` ставить "12:00 UTC, щоб
    уникнути багів зміни дня через таймзони").

    tz-aware datetime тут НАВМИСНО конвертуємо в Київ ПЕРЕД .date():
    Firestore повертає Timestamp як datetime в UTC, і голий .date() на
    ньому дав би невірну добу для будь-якого значення, записаного біля
    півночі за Києвом (той самий клас бага, від якого рятує опівдні, але
    тут — про читання, а не про запис: якщо колись хтось у Rowy проставить
    час, відмінний від "безпечної" середини дня, .date() без конвертації
    в Київ уже не врятує).

    Мовчки ковтати криве значення тут правильно: календар редагують руками
    в Rowy, і один зіпсований запис не має валити сторінку — він має
    випасти з покриття, що потім побачить `validate()`.
    """
    if isinstance(value, datetime):
        moment = value if value.tzinfo else value.replace(tzinfo=KYIV)
        return moment.astimezone(KYIV).date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        # Рядки лишаються як фолбек: старі документи (до переходу на
        # Timestamp) і ручний правопис у Rowy повз UI дати досі мають
        # парситись, а не випадати з покриття.
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


class Segment:
    """Один відрізок календаря. `to` — ВКЛЮЧНО."""

    __slots__ = ("kind", "start", "end", "semester")

    def __init__(self, kind: str, start: date, end: date, semester: str):
        self.kind = kind
        self.start = start
        self.end = end
        self.semester = semester

    def contains(self, day: date) -> bool:
        return self.start <= day <= self.end

    @property
    def weeks(self) -> int:
        return ((self.end - self.start).days + 1) // 7

    def __repr__(self) -> str:
        return f"<{self.kind} {self.start}..{self.end} {self.semester}>"


class Calendar:
    """Розібраний календар. Усі методи СИНХРОННІ й чисті — асинхронне тут
    лише саме читання документа (`load()` нижче).

    Порожній календар (документа немає, або він кривий) — легальний стан:
    усі методи віддають None/порожнє, і виклична сторона відкочується на
    стару вільнотекстову конфігурацію. Зникнення документа не має ламати
    привітальне повідомлення.
    """

    def __init__(self, raw: dict | None = None):
        raw = raw or {}
        self.year: str = (raw.get("year") or "").strip()
        self.analytics: dict = raw.get("analytics") or {}
        # Широкі межі семестру (Shopping Week -> кінець навчання), як їх
        # пише школа. Є лише в новому форматі; для старого — див.
        # semester_bounds(), що виводить їх із сегментів.
        self.bounds: dict[str, tuple[date, date]] = {}
        segments = []

        def add(item, semester):
            if not isinstance(item, dict):
                return
            start, end = _as_date(item.get("from")), _as_date(item.get("to"))
            kind = (item.get("kind") or "").strip()
            kind = _KIND_ALIASES.get(kind, kind)
            semester = (semester or "").strip()
            if start and end and kind and start <= end:
                segments.append(Segment(kind, start, end, semester))

        if isinstance(raw.get("semesters"), list):
            for sem in raw["semesters"]:
                if not isinstance(sem, dict):
                    continue
                code = (sem.get("code") or "").strip()
                low, high = _as_date(sem.get("from")), _as_date(sem.get("to"))
                if code and low and high and low <= high:
                    self.bounds[code] = (low, high)
                for period in sem.get("periods") or []:
                    add(period, code)
            for item in raw.get("breaks") or []:
                add(item, item.get("semester") if isinstance(item, dict) else "")
        else:
            for item in raw.get("segments") or []:
                add(item, item.get("semester") if isinstance(item, dict) else "")
        segments.sort(key=lambda s: s.start)
        self.segments: list[Segment] = segments

    def __bool__(self) -> bool:
        return bool(self.segments)

    # --- Сегменти ---------------------------------------------------------

    def segment_on(self, day: date | None = None) -> Segment | None:
        day = day or today()
        for segment in self.segments:
            if segment.contains(day):
                return segment
        return None

    def next_segment(self, kind: str, after: date | None = None) -> Segment | None:
        """Найближчий сегмент цього типу, що ПОЧИНАЄТЬСЯ не раніше `after`.

        Саме "починається", а не "триває": підставляючи в привітальне
        повідомлення дату Induction Week, ми маємо на увазі "коли він
        стартує", і для людини, яку схвалили в середу вступного тижня,
        коректна відповідь — той самий тиждень, а не наступний рік.
        Тому поточний сегмент теж підходить, якщо він ще не почався... а
        якщо вже триває — віддаємо його ж, бо "стартує" вже сталося.
        """
        after = after or today()
        current = self.segment_on(after)
        if current is not None and current.kind == kind:
            return current
        for segment in self.segments:
            if segment.kind == kind and segment.start >= after:
                return segment
        return None

    def is_holiday(self, day: date | None = None) -> bool:
        """Канікули в широкому сенсі — уроків немає (і міжсеместрові, і літні)."""
        segment = self.segment_on(day)
        return segment is not None and segment.kind in BREAK_KINDS

    def is_summer(self, day: date | None = None) -> bool:
        segment = self.segment_on(day)
        return segment is not None and segment.kind == KIND_SUMMER

    # --- Семестри ---------------------------------------------------------

    def all_semesters(self) -> list[str]:
        """Коди семестрів у хронологічному порядку, без повторів."""
        seen: list[str] = []
        for segment in self.segments:
            if segment.semester and segment.semester not in seen:
                seen.append(segment.semester)
        return seen

    def semester_range(self, code: str) -> tuple[date, date] | None:
        """(перший день, останній день) семестру — включно.

        Без правил-здогадок: просто межі всіх сегментів із цим кодом.
        Оскільки канікули несуть код НАСТУПНОГО семестру, вікно автоматично
        починається з першого дня канікул перед ним (тобто з відкриття набору).
        """
        days = [s for s in self.segments if s.semester == code]
        if not days:
            return None
        return min(s.start for s in days), max(s.end for s in days)

    def semester_bounds(self, code: str) -> tuple[date, date] | None:
        """Широкі межі семестру: від початку Shopping Week до останнього дня
        навчання — так, як семестр називає школа.

        НЕ плутати з semester_range(): той — усе, що належить семестру,
        включно з набором перед ним, і саме він є вікном когорти для
        аналітики (заявка, подана на канікулах, — заявка на цей семестр).
        """
        if code in self.bounds:
            return self.bounds[code]
        shopping = [s.start for s in self.segments if s.semester == code and s.kind == KIND_SHOPPING]
        term = [s.end for s in self.segments if s.semester == code and s.kind == KIND_TERM]
        return (min(shopping), max(term)) if shopping and term else None

    def semester_containing(self, day: date | None = None) -> str | None:
        segment = self.segment_on(day)
        return segment.semester or None if segment else None

    def current_semester(self, day: date | None = None) -> str | None:
        return self.semester_containing(day)

    def previous_semester(self, code: str) -> str | None:
        codes = self.all_semesters()
        if code not in codes:
            return None
        index = codes.index(code)
        return codes[index - 1] if index > 0 else None

    def term_week_index(self, day: date | None = None) -> int | None:
        """Номер тижня ВСЕРЕДИНІ семестру (1-based), або None поза семестром.

        Вісь для трендів і когортних теплокарт: ISO-тижні тут читаються гірше,
        бо не збігаються з межами семестру, і графік не можна порівняти
        "тиждень 3 цього семестру проти тижня 3 попереднього".
        """
        day = day or today()
        code = self.semester_containing(day)
        if not code:
            return None
        window = self.semester_range(code)
        if not window:
            return None
        return (day - window[0]).days // 7 + 1

    # --- Дати для текстів -------------------------------------------------

    def induction_start(self, after: date | None = None) -> date | None:
        segment = self.next_segment(KIND_INDUCTION, after)
        return segment.start if segment else None

    def term_start(self, after: date | None = None) -> date | None:
        """Коли для новачка починається навчання.

        Це Shopping Week, а не `term`: саме її дата стоїть у теперішньому
        `termStartDate` ("14 вересня" = понеділок Shopping Week), тож
        зміна джерела не має мовчки посунути текст на тиждень уперед.
        """
        segment = self.next_segment(KIND_SHOPPING, after)
        return segment.start if segment else None

    def next_intake_start(self, after: date | None = None) -> date | None:
        """Коли відкривається набір на наступний семестр — перший день
        найближчих МІЖСЕМЕСТРОВИХ канікул (див. докстрінг модуля).

        Літні свідомо не рахуються: це кінець року, а не пауза між наборами.
        Після останнього семестру функція віддає None, і виклична сторона
        відкочується на ручний `nextRegistrationDate` — дату наступного
        навчального року все одно призначає овнер, а не календар."""
        segment = self.next_segment(KIND_ADMISSION, after)
        return segment.start if segment else None

    # --- Аналітичні налаштування -----------------------------------------

    def velocity_baseline_from(self) -> date | None:
        """Дата, раніше за яку часові метрики ігнорують переходи.

        Перші дні після запуску системи чекали на API-інтеграцію зі
        SchoolToday, тож заявки лежали нерозглянутими добами й тягнули
        медіану з середнім. Це ВИКЛЮЧЕННЯ, а не видалення: самі заявки
        лишаються у воронці й у конверсії, бо вони справді її пройшли.
        """
        return _as_date(self.analytics.get("velocityBaselineFrom"))

    def trimmed_mean_percent(self) -> float:
        value = self.analytics.get("trimmedMeanPercent")
        return float(value) if isinstance(value, (int, float)) else 5.0

    def trim_min_sample(self) -> int:
        value = self.analytics.get("trimMinSample")
        return int(value) if isinstance(value, (int, float)) else 20

    # --- Самоперевірка ----------------------------------------------------

    def validate(self) -> list[str]:
        """Проблеми покриття людською мовою. Порожній список — усе гаразд.

        Використовує і скрипт заливки (щоб не залити діряве), і тест.
        """
        problems = []
        if not self.segments:
            return ["календар порожній"]
        for segment in self.segments:
            if segment.kind not in SEGMENT_KINDS:
                problems.append(f"невідомий тип сегмента: {segment.kind} ({segment.start})")
            if not segment.semester:
                problems.append(f"сегмент без семестру: {segment.kind} {segment.start}")
        for previous, nxt in zip(self.segments, self.segments[1:]):
            gap = (nxt.start - previous.end).days
            if gap > 1:
                problems.append(f"дірка {previous.end} -> {nxt.start} ({gap - 1} дн)")
            elif gap < 1:
                problems.append(f"перекриття {previous} і {nxt}")
        # Межі семестру — рівно від Shopping Week до кінця навчання: дві
        # копії однієї дати в документі мусять збігатись, інакше незрозуміло,
        # якій вірити.
        for code, (low, high) in self.bounds.items():
            shopping = [s.start for s in self.segments if s.semester == code and s.kind == KIND_SHOPPING]
            term = [s.end for s in self.segments if s.semester == code and s.kind == KIND_TERM]
            if not shopping or not term:
                problems.append(f"{code}: немає shopping або term")
                continue
            if low != min(shopping):
                problems.append(f"{code}: межа from {low} ≠ початок Shopping Week {min(shopping)}")
            if high != max(term):
                problems.append(f"{code}: межа to {high} ≠ кінець навчання {max(term)}")
        return problems


# --- Форматування дат -----------------------------------------------------


def format_date(day: date | None, lang: str = "uk", with_weekday: bool = True) -> str:
    """«понеділок, 7 вересня 2026 року» / «Monday, 7 September 2026».

    Формат навмисно збігається з тим, що стояло у вільнотекстовому
    `inductionStartDate`, щоб перехід на календар не змінив текст
    привітального повідомлення для студента.
    """
    if not day:
        return "—"
    if lang == "en":
        body = f"{day.day} {_EN_MONTHS[day.month - 1]} {day.year}"
        return f"{_EN_WEEKDAYS[day.weekday()]}, {body}" if with_weekday else body
    body = f"{day.day} {_UK_MONTHS_GEN[day.month - 1]} {day.year} року"
    return f"{_UK_WEEKDAYS[day.weekday()]}, {body}" if with_weekday else body


def format_range(window: tuple[date, date] | None, lang: str = "uk") -> str:
    """«02.11.2026 – 20.12.2026». Короткий формат: це підпис фільтра, а не
    речення в листі."""
    if not window:
        return "—"
    start, end = window
    return f"{start.strftime('%d.%m.%Y')} – {end.strftime('%d.%m.%Y')}"


def today() -> date:
    """Сьогодні ЗА КИЄВОМ. На Cloud Run процес живе в UTC, і date.today()
    там перемикає добу на 2-3 години раніше, ніж у школи."""
    return datetime.now(KYIV).date()


def to_kyiv_bounds(window: tuple[date, date]) -> tuple[datetime, datetime]:
    """Дати -> межі для фільтрів аналітики: початок першої доби і кінець
    останньої, обидві за Києвом (там же, де мітки часу бота)."""
    start, end = window
    return (
        datetime(start.year, start.month, start.day, tzinfo=KYIV),
        datetime(end.year, end.month, end.day, tzinfo=KYIV) + timedelta(days=1) - timedelta(microseconds=1),
    )


# --- Читання з кешем ------------------------------------------------------
#
# Той самий підхід, що в get_maintenance_mode: документ крихітний і майже
# ніколи не міняється, але потрібен на КОЖЕН рендер дашборда й на кожне
# схвалення заявки. TTL більший (10 хв), бо календар правлять раз на рік.
_CACHE: "tuple[float, Calendar] | None" = None
_TTL = 600.0
_LOCK = asyncio.Lock()


async def load_calendar() -> Calendar:
    global _CACHE
    if _CACHE and time.monotonic() < _CACHE[0]:
        return _CACHE[1]

    async with _LOCK:
        if _CACHE and time.monotonic() < _CACHE[0]:
            return _CACHE[1]
        try:
            doc = await db.collection(CALENDAR_DOC[0]).document(CALENDAR_DOC[1]).get()
            raw = doc.to_dict() if doc.exists else None
        except Exception:
            # Календар — не критичний шлях: без нього панель має працювати
            # на старій вільнотекстовій конфігурації, а не віддавати 500.
            logging.exception("Не вдалося прочитати Config/academic_calendar")
            raw = None
        calendar = Calendar(raw)
        if raw and (problems := calendar.validate()):
            logging.warning("Календар має проблеми покриття: %s", "; ".join(problems))
        _CACHE = (time.monotonic() + _TTL, calendar)
        return calendar


def invalidate_calendar_cache() -> None:
    """Після редагування календаря — щоб зміна діяла одразу, а не через TTL."""
    global _CACHE
    _CACHE = None
