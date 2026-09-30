"""Логічні перевірки реєстрації за календарем — без жодних запитів у мережу.

Ганяє чисті функції `core.registration`: розбір дати з /registration,
стан (відкрита / ручний перемикач / наступний набір) і перенесення старту
набору в документі календаря.

    python -m scripts.test_registration
"""
import sys
from datetime import date

from dotenv import load_dotenv

load_dotenv()

sys.stdout.reconfigure(encoding="utf-8")

from core.academic_calendar import Calendar, _as_date, to_kyiv_bounds  # noqa: E402
from core.registration import parse_day, plan_admission_move, resolve_state  # noqa: E402

_fails = 0


def check(label: str, got, want) -> None:
    global _fails
    ok = got == want
    _fails += not ok
    print(f"  [{'OK ' if ok else 'FAIL'}] {label}: {got!r}" + ("" if ok else f"  (очікували {want!r})"))


def raises(label: str, fn) -> None:
    global _fails
    try:
        fn()
    except ValueError as e:
        print(f"  [OK ] {label}: {e}")
        return
    _fails += 1
    print(f"  [FAIL] {label}: не кинуло ValueError")


def _p(kind, first, last):
    start, _ = to_kyiv_bounds((date(*first), date(*first)))
    _, end = to_kyiv_bounds((date(*last), date(*last)))
    return {"kind": kind, "from": start, "to": end}


def _sem(code, *periods):
    shopping = next(p for p in periods if p["kind"] == "shopping")
    term = next(p for p in periods if p["kind"] == "term")
    return {"code": code, "from": shopping["from"], "to": term["to"], "periods": list(periods)}


# Шматок справжнього календаря 2026-27 (scripts/seed_academic_calendar.py у панелі).
RAW = {
    "semesters": [
        _sem("26-27_01",
             _p("admission", (2026, 8, 25), (2026, 9, 6)),
             _p("induction", (2026, 9, 7), (2026, 9, 13)),
             _p("shopping", (2026, 9, 14), (2026, 9, 20)),
             _p("term", (2026, 9, 21), (2026, 10, 25))),
        _sem("26-27_02",
             _p("admission", (2026, 10, 26), (2026, 11, 1)),
             _p("shopping", (2026, 11, 2), (2026, 11, 8)),
             _p("term", (2026, 11, 9), (2026, 12, 13)),
             _p("christmas", (2026, 12, 14), (2026, 12, 20))),
        _sem("26-27_03",
             _p("admission", (2026, 12, 21), (2027, 1, 3)),
             _p("shopping", (2027, 1, 4), (2027, 1, 10)),
             _p("term", (2027, 1, 11), (2027, 2, 14))),
    ],
    "breaks": [],
}
CAL = Calendar(RAW)
check("вихідний календар валідний", CAL.validate(), [])

print("\nparse_day")
today = date(2026, 9, 30)
check("25.10", parse_day("25.10", today), date(2026, 10, 25))
check("25 жовтня", parse_day("25 жовтня", today), date(2026, 10, 25))
check("25 жовтень (називний)", parse_day("25 жовтень", today), date(2026, 10, 25))
check("25 жовтня 2026 року", parse_day("25 жовтня 2026 року", today), date(2026, 10, 25))
check("2026-10-25", parse_day("2026-10-25", today), date(2026, 10, 25))
check("25.10.26", parse_day("25.10.26", today), date(2026, 10, 25))
check("у грудні 05.01 — це наступний рік", parse_day("05.01", date(2026, 12, 20)), date(2027, 1, 5))
check("сьогодні — ще цей рік", parse_day("30.09", today), date(2026, 9, 30))
check("сміття", parse_day("завтра", today), None)
check("31.02 не існує", parse_day("31.02", today), None)

print("\nresolve_state")
st = resolve_state(CAL, None, date(2026, 9, 30))
check("term — закрито", st.is_open, False)
check("term — наступний набір 26.10 на 02", (st.next_start, st.next_semester), (date(2026, 10, 26), "26-27_02"))
st = resolve_state(CAL, None, date(2026, 10, 28))
check("admission — відкрито до 01.11", (st.is_open, st.manual, st.until), (True, False, date(2026, 11, 1)))
st = resolve_state(CAL, {"open": False, "until": "2026-11-01"}, date(2026, 10, 28))
check("вручну закрито в admission", (st.is_open, st.manual), (False, True))
check("…і наступний набір — уже після цього", st.next_start, date(2026, 12, 21))
st = resolve_state(CAL, {"open": False, "until": "2026-11-01"}, date(2026, 11, 2))
check("ручне закрито скінчилось 01.11 — далі календар", (st.is_open, st.manual), (False, False))
st = resolve_state(CAL, {"open": True, "until": "2026-10-25"}, date(2026, 10, 20))
check("вручну відкрито в term", (st.is_open, st.manual, st.until), (True, True, date(2026, 10, 25)))
st = resolve_state(Calendar(None), None, date(2026, 10, 28))
check("без календаря — закрито", (st.is_open, st.calendar_ok, st.next_start), (False, False, None))
st = resolve_state(Calendar(None), {"open": True, "until": None}, date(2026, 10, 28))
check("без календаря, вручну відкрито безстроково", (st.is_open, st.manual), (True, True))

print("\nplan_admission_move")
doc, move = plan_admission_move(RAW, date(2026, 10, 25), today)
cal = Calendar(doc)
check("семестр", move.semester, "26-27_02")
check("було/стало", (move.old_start, move.new_start), (date(2026, 10, 26), date(2026, 10, 25)))
check("попередній — term 01, кінець 25.10 -> 24.10",
      (move.previous_kind, move.previous_semester, move.previous_old_end, move.previous_new_end),
      ("term", "26-27_01", date(2026, 10, 25), date(2026, 10, 24)))
check("після перенесення календар валідний", cal.validate(), [])
check("25.10 — уже набір, семестр 02", (cal.segment_on(date(2026, 10, 25)).kind,
                                          cal.current_semester(date(2026, 10, 25))), ("admission", "26-27_02"))
check("24.10 — ще term 01", cal.current_semester(date(2026, 10, 24)), "26-27_01")
check("вікно аналітики 02 стартує 25.10", cal.semester_range("26-27_02")[0], date(2026, 10, 25))
check("межа семестру 01 теж зсунулась", cal.semester_bounds("26-27_01"), (date(2026, 9, 14), date(2026, 10, 24)))
admission = doc["semesters"][1]["periods"][0]
check("планова дата збережена в movedFrom", _as_date(admission["movedFrom"]), date(2026, 10, 26))
check("вихідний документ не змінено", _as_date(RAW["semesters"][1]["periods"][0]["from"]), date(2026, 10, 26))
check("реєстрація 25.10 відкрита сама", resolve_state(cal, None, date(2026, 10, 25)).is_open, True)
check("24.10 ще закрита, набір — 25.10", resolve_state(cal, None, date(2026, 10, 24)).next_start, date(2026, 10, 25))

doc2, _ = plan_admission_move(doc, date(2026, 10, 26), today)
check("повернули на планову — movedFrom прибрано", "movedFrom" in doc2["semesters"][1]["periods"][0], False)
check("…і term 01 знову до 25.10", Calendar(doc2).semester_bounds("26-27_01")[1], date(2026, 10, 25))

doc3, move3 = plan_admission_move(RAW, date(2026, 10, 28), today)
check("пізніший старт: term 01 довшає до 27.10", move3.previous_new_end, date(2026, 10, 27))
check("пізніший старт валідний", Calendar(doc3).validate(), [])

doc4, move4 = plan_admission_move(RAW, date(2026, 12, 19), date(2026, 10, 28))
check("під час набору 02 переноситься вже набір 03", move4.semester, "26-27_03")
check("перед 03 іде christmas 02", (move4.previous_kind, move4.previous_new_end), ("christmas", date(2026, 12, 18)))

raises("дата в минулому", lambda: plan_admission_move(RAW, date(2026, 9, 29), today))
raises("та сама дата", lambda: plan_admission_move(RAW, date(2026, 10, 26), today))
raises("пізніше за кінець набору", lambda: plan_admission_move(RAW, date(2026, 11, 2), today))
raises("раніше за початок term", lambda: plan_admission_move(RAW, date(2026, 9, 21), date(2026, 9, 21)))
raises("попереду немає набору", lambda: plan_admission_move(RAW, date(2027, 1, 20), date(2027, 1, 20)))

print(f"\n{'✅ Усе гаразд' if not _fails else f'❌ Провалів: {_fails}'}")
sys.exit(1 if _fails else 0)
