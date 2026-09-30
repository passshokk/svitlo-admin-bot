# core/registration.py
"""Реєстрація нових лідів: чи вона відкрита зараз і коли стартує набір.

Єдине джерело дат — навчальний календар (Config/academic_calendar).
Реєстрація відкрита рівно тоді, коли сьогодні (за Києвом) припадає на
період `admission`. До 30.09.2026 тут були три ручні поля в
Config/bot_settings (`registrationOpen`, `nextRegistrationDate`,
`currentSemester`), і вони розходились із календарем: у полі стояло
«25 жовтня», календар казав 26-те, а аналітика рахувала семестр по
календарю.

Ранній (чи пізній) старт набору — це правка КАЛЕНДАРЯ, а не окреме поле.
`/registration 25.10` переносить початок найближчого admission на 25.10, а
попередній період (зазвичай term) коротшає до 24.10. Від однієї дати разом
рушать і реєстрація, і семестр, який отримує новий лід, і вікно семестру в
аналітиці панелі. Окремий прапорець «набір з 25.10» довелося б навчити
кожного з них, і рано чи пізно хтось про нього забув би. Планова дата
лишається в самому періоді (`movedFrom`), щоб було видно, що старт
переносили.

Ручний перемикач (`registrationOverride` у Config/bot_settings) —
ТИМЧАСОВИЙ: діє до кінця поточного періоду календаря, далі знову рішає
календар. Безстроковий «закрито», про який забули, мовчки не відкрив би
наступний набір, і помітили б це лише по порожній воронці.
"""
import copy
import logging
import re
from datetime import date, timedelta
from typing import NamedTuple

from google.api_core.exceptions import FailedPrecondition
from google.cloud import firestore

from core.academic_calendar import (
    _KIND_ALIASES,
    _UK_MONTHS_GEN,
    CALENDAR_DOC,
    KIND_ADMISSION,
    Calendar,
    _as_date,
    format_date,
    invalidate_calendar_cache,
    load_calendar,
    to_kyiv_bounds,
    today,
)
from core.database import db

_SETTINGS_DOC = ("Config", "bot_settings")
_OVERRIDE_FIELD = "registrationOverride"


# --- Стан реєстрації ------------------------------------------------------


class RegistrationState(NamedTuple):
    is_open: bool
    # True — стан задано вручну (/registration), False — за календарем.
    manual: bool
    # Останній день поточного стану: кінець ручного перемикання або кінець
    # набору, що зараз триває. None — невідомо (немає календаря).
    until: date | None
    # Коли відкриється наступний набір і на який семестр — лише для закритої.
    next_start: date | None
    next_semester: str | None
    calendar_ok: bool


def _active_override(raw, day: date) -> dict | None:
    """{"open": bool, "until": date | None}, якщо ручне перемикання ще діє."""
    if not isinstance(raw, dict) or not isinstance(raw.get("open"), bool):
        return None
    until = _as_date(raw.get("until"))
    if until is not None and day > until:
        return None
    return {"open": raw["open"], "until": until}


def resolve_state(calendar: Calendar, override_raw, day: date) -> RegistrationState:
    """Чистий розрахунок стану — без жодних запитів (його ганяє тест)."""
    segment = calendar.segment_on(day) if calendar else None
    in_admission = segment is not None and segment.kind == KIND_ADMISSION
    override = _active_override(override_raw, day)

    if override:
        is_open, until = override["open"], override["until"]
    else:
        is_open = in_admission
        until = segment.end if in_admission else None

    next_start = next_semester = None
    if not is_open and calendar:
        # Наступний набір — перший, що починається ПІСЛЯ закритого відрізка.
        # Якщо набір зараз триває, але його закрили вручну до кінця, то
        # «наступний» — уже той, що після нього, а не сьогоднішній.
        reference = until if override and until else day
        for candidate in calendar.segments:
            if candidate.kind == KIND_ADMISSION and candidate.start > reference:
                next_start, next_semester = candidate.start, candidate.semester
                break

    return RegistrationState(
        is_open=is_open,
        manual=override is not None,
        until=until,
        next_start=next_start,
        next_semester=next_semester,
        calendar_ok=bool(calendar),
    )


async def _read_override():
    doc = await db.collection(_SETTINGS_DOC[0]).document(_SETTINGS_DOC[1]).get()
    return (doc.to_dict() or {}).get(_OVERRIDE_FIELD) if doc.exists else None


async def get_state() -> RegistrationState:
    return resolve_state(await load_calendar(), await _read_override(), today())


async def is_registration_open() -> bool:
    """Чи бачать нові ліди кнопку «Хочу зареєструватись» і чи йдуть їм
    нагадування. Без календаря — закрита: краще тимчасово не пустити, ніж
    записати людей у семестр навмання."""
    return (await get_state()).is_open


async def next_registration_text() -> str | None:
    """«26 жовтня 2026 року» — для кнопки-блокера, коли реєстрація закрита.
    None — дати немає (реєстрація відкрита, або календар її не знає, як
    влітку: набір наступного року з'явиться разом із його календарем)."""
    state = await get_state()
    if state.is_open or not state.next_start:
        return None
    return format_date(state.next_start, with_weekday=False)


async def set_override(is_open: bool | None) -> RegistrationState:
    """Ручне перемикання до кінця поточного періоду календаря.
    None — повернути керування календарю."""
    ref = db.collection(_SETTINGS_DOC[0]).document(_SETTINGS_DOC[1])
    if is_open is None:
        # update, а не set(merge) з DELETE_FIELD: документ точно існує —
        # у ньому живе список тестувальників.
        await ref.update({_OVERRIDE_FIELD: firestore.DELETE_FIELD})
    else:
        calendar = await load_calendar()
        segment = calendar.segment_on(today()) if calendar else None
        await ref.set({_OVERRIDE_FIELD: {
            "open": is_open,
            # Без календаря кінця періоду не знати — тоді безстроково,
            # а статус /registration про це скаже.
            "until": segment.end.isoformat() if segment else None,
        }}, merge=True)
    return await get_state()


# --- Розбір дати з команди ------------------------------------------------


def parse_day(text: str, day: date) -> date | None:
    """«25.10», «25.10.2026», «2026-10-25», «25 жовтня», «25 жовтня 2026».

    Рік не вказано — береться найближча така дата не раніше сьогодні:
    у грудні «05.01» — це вже наступний рік."""
    text = (text or "").strip().lower().rstrip(".")
    text = re.sub(r"\s*(року|р)$", "", text)
    year = month = dom = None

    if m := re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", text):
        year, month, dom = int(m[1]), int(m[2]), int(m[3])
    elif m := re.fullmatch(r"(\d{1,2})[./](\d{1,2})(?:[./](\d{2}|\d{4}))?", text):
        dom, month = int(m[1]), int(m[2])
        if m[3]:
            year = int(m[3]) + (2000 if len(m[3]) == 2 else 0)
    elif m := re.fullmatch(r"(\d{1,2})\s+([а-яіїєґʼ']+)(?:\s+(\d{4}))?", text):
        dom = int(m[1])
        # Перших трьох літер досить, щоб розрізнити всі місяці, і тоді
        # проходить і «жовтня», і «жовтень».
        month = next((i + 1 for i, name in enumerate(_UK_MONTHS_GEN)
                      if name[:3] == m[2][:3]), None)
        year = int(m[3]) if m[3] else None
    if not month:
        return None

    try:
        if year:
            return date(year, month, dom)
        candidate = date(day.year, month, dom)
        return candidate if candidate >= day else date(day.year + 1, month, dom)
    except ValueError:
        return None


# --- Перенесення старту набору --------------------------------------------


class AdmissionMove(NamedTuple):
    semester: str
    old_start: date
    new_start: date
    # Період перед набором, що коротшає (чи довшає): kind, семестр, кінець до і після.
    previous_kind: str | None
    previous_semester: str | None
    previous_old_end: date | None
    previous_new_end: date | None


def _kind(item: dict) -> str:
    kind = (item.get("kind") or "").strip()
    return _KIND_ALIASES.get(kind, kind)


def plan_admission_move(raw: dict, new_start: date, day: date) -> tuple[dict, AdmissionMove]:
    """Нова версія документа календаря, де найближчий набір стартує `new_start`.

    Чиста функція: нічого не пише, лише повертає змінену КОПІЮ і опис змін.
    Кидає ValueError з людським поясненням, якщо перенести не можна.

    «Найближчий» — перший набір, що ще НЕ почався. Той, що вже триває,
    не чіпаємо: заднім числом переписати початок означало б перекинути вже
    зареєстрованих лідів в аналітиці в інший семестр.
    """
    doc = copy.deepcopy(raw or {})
    # (семестр-власник або None для breaks, сам період)
    entries = [(sem, period)
               for sem in doc.get("semesters") or [] if isinstance(sem, dict)
               for period in sem.get("periods") or [] if isinstance(period, dict)]
    entries += [(None, item) for item in doc.get("breaks") or [] if isinstance(item, dict)]

    upcoming = sorted(
        ((_as_date(p.get("from")), sem, p) for sem, p in entries
         if _kind(p) == KIND_ADMISSION and _as_date(p.get("from"))
         and _as_date(p.get("from")) > day),
        key=lambda row: row[0],
    )
    if not upcoming:
        raise ValueError("У календарі попереду немає жодного набору. Якщо зараз літо, "
                         "спершу потрібен календар наступного навчального року.")
    old_start, owner, admission = upcoming[0]
    code = ((owner or {}).get("code") or admission.get("semester") or "").strip()
    old_end = _as_date(admission.get("to"))

    if new_start < day:
        raise ValueError("Ця дата вже минула.")
    if new_start == old_start:
        raise ValueError(f"Набір на {code} і так стартує {old_start:%d.%m.%Y}.")
    if old_end and new_start > old_end:
        raise ValueError(f"Набір на {code} закінчується {old_end:%d.%m.%Y}, "
                         "стартувати пізніше за це не вийде.")

    move = dict(semester=code, old_start=old_start, new_start=new_start,
                previous_kind=None, previous_semester=None,
                previous_old_end=None, previous_new_end=None)

    # Період, що впритул перед набором, мусить зсунути свій кінець, інакше
    # вийде перекриття (раніше) або дірка (пізніше) — і validate() зламається.
    previous = next(((sem, p) for sem, p in entries
                     if _as_date(p.get("to")) == old_start - timedelta(days=1)), None)
    if previous:
        prev_owner, prev_item = previous
        prev_start, prev_end = _as_date(prev_item.get("from")), _as_date(prev_item.get("to"))
        if prev_start and new_start <= prev_start:
            raise ValueError(f"Перед набором іде {_kind(prev_item)} з {prev_start:%d.%m.%Y}. "
                             "Раніше за його початок набір не перенести.")
        new_prev_end = new_start - timedelta(days=1)
        prev_item["to"] = to_kyiv_bounds((new_prev_end, new_prev_end))[1]
        prev_code = (prev_owner or {}).get("code") or prev_item.get("semester") or ""
        # Межа семестру (`to` = кінець навчання) — друга копія тієї самої
        # дати. Якщо вона дивилась на цей період, рухаємо й її.
        if prev_owner is not None and _as_date(prev_owner.get("to")) == prev_end:
            prev_owner["to"] = prev_item["to"]
        move.update(previous_kind=_kind(prev_item), previous_semester=prev_code,
                    previous_old_end=prev_end, previous_new_end=new_prev_end)

    # Планова дата зберігається лише раз — при першому перенесенні. Повернули
    # на неї ж — позначка більше не потрібна.
    planned = admission.get("movedFrom", admission.get("from"))
    admission["from"] = to_kyiv_bounds((new_start, new_start))[0]
    if _as_date(planned) == new_start:
        admission.pop("movedFrom", None)
    else:
        admission["movedFrom"] = planned

    problems = set(Calendar(doc).validate()) - set(Calendar(raw).validate())
    if problems:
        raise ValueError("Календар після перенесення не проходить перевірку: "
                         + "; ".join(sorted(problems)))
    return doc, AdmissionMove(**move)


def _calendar_ref():
    return db.collection(CALENDAR_DOC[0]).document(CALENDAR_DOC[1])


async def preview_admission_move(new_start: date) -> AdmissionMove:
    """Що зміниться — без запису (для кроку підтвердження)."""
    snap = await _calendar_ref().get()
    if not snap.exists:
        raise ValueError("Документа Config/academic_calendar немає.")
    return plan_admission_move(snap.to_dict() or {}, new_start, today())[1]


async def move_admission_start(new_start: date) -> AdmissionMove:
    ref = _calendar_ref()
    snap = await ref.get()
    if not snap.exists:
        raise ValueError("Документа Config/academic_calendar немає.")
    raw = snap.to_dict() or {}
    doc, move = plan_admission_move(raw, new_start, today())
    fields = {key: doc[key] for key in ("semesters", "breaks") if key in raw}
    try:
        # Лише якщо документ не змінився від читання: інакше можна затерти
        # ручну правку в консолі, зроблену тієї ж хвилини.
        await ref.update(fields, option=db.write_option(last_update_time=snap.update_time))
    except FailedPrecondition:
        raise ValueError("Календар щойно змінили в іншому місці. Спробуй ще раз.")
    invalidate_calendar_cache()
    # Ручне перемикання рахувало свій термін від старих меж періодів: «закрито
    # до 24.10» після перенесення набору на 20.10 тримало б реєстрацію
    # закритою саме тоді, коли її щойно призначили відкрити.
    await db.collection(_SETTINGS_DOC[0]).document(_SETTINGS_DOC[1]).update(
        {_OVERRIDE_FIELD: firestore.DELETE_FIELD})
    logging.info("Набір на %s перенесено: %s -> %s", move.semester, move.old_start, move.new_start)
    return move
