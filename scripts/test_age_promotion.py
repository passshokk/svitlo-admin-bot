"""Логічні перевірки вікового переведення — без жодних запитів у мережу.

Ганяє `core.utils.calculate_age` на межових датах і `core.age_promotion.
select_promotable` на вигаданій вибірці.

    python -m scripts.test_age_promotion
"""
import sys
from datetime import date, datetime, timezone

from dotenv import load_dotenv

load_dotenv()  # core.age_promotion -> core.bot_init читає BOT_TOKEN при імпорті

sys.stdout.reconfigure(encoding="utf-8")

from core.age_promotion import select_promotable  # noqa: E402
from core.utils import calculate_age  # noqa: E402

_fails = 0


def check(label: str, got, want) -> None:
    global _fails
    ok = got == want
    _fails += not ok
    print(f"  [{'OK ' if ok else 'FAIL'}] {label}: {got!r}" + ("" if ok else f"  (очікували {want!r})"))


print("calculate_age")
today = date(2026, 9, 2)
check("рівно 14 сьогодні (ДН 2012-09-02)", calculate_age(date(2012, 9, 2), today), 14)
check("14 буде завтра (ДН 2012-09-03)", calculate_age(date(2012, 9, 3), today), 13)
check("13 (ДН 2013-01-10)", calculate_age(date(2013, 1, 10), today), 13)
check("Firestore-подібний datetime 12:00 UTC", calculate_age(datetime(2012, 9, 2, 12, tzinfo=timezone.utc), today), 14)
check("рядок ISO", calculate_age("2012-09-02", today), 14)
check("рядок ISO з часом", calculate_age("2012-09-02T00:00:00+00:00", today), 14)
check("29 лютого (ДН 2012-02-29)", calculate_age(date(2012, 2, 29), today), 14)
check("None на порожньому", calculate_age(None, today), None)
check("None на смітті", calculate_age("не дата", today), None)


print("\nselect_promotable")
docs = [
    {"_id": "A", "ageGroup": "younger", "stage": "student", "birthDate": datetime(2012, 1, 1, 12, tzinfo=timezone.utc)},   # 14 -> перевести
    {"_id": "B", "ageGroup": "younger", "stage": "student", "birthDate": datetime(2014, 1, 1, 12, tzinfo=timezone.utc)},   # 12 -> ні
    {"_id": "C", "ageGroup": "older",   "stage": "student", "birthDate": datetime(2012, 1, 1, 12, tzinfo=timezone.utc)},   # вже older
    {"_id": "D", "ageGroup": "younger", "stage": "lead",    "birthDate": datetime(2012, 1, 1, 12, tzinfo=timezone.utc)},   # не зарахований
    {"_id": "E", "ageGroup": "younger", "stage": "student", "birthDate": None},                                            # без ДН
    {"_id": "F", "ageGroup": "younger", "stage": "student", "birthDate": datetime(2005, 1, 1, 12, tzinfo=timezone.utc)},   # 21 -> аномалія, але перевести
]
promote, no_birthdate, anomalies = select_promotable(docs, today)
check("на переведення", sorted(d["_id"] for d, _ in promote), ["A", "F"])
check("без дати народження", [d["_id"] for d in no_birthdate], ["E"])
check("аномалії (вік > 18)", [d["_id"] for d, _ in anomalies], ["F"])

print()
if _fails:
    print(f"❌ Провалено перевірок: {_fails}")
    sys.exit(1)
print("✅ Усі перевірки пройдені")
