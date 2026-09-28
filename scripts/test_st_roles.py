# scripts/test_st_roles.py
"""Ролі Firestore -> поле «Ролі» в SchoolToday (core.schooltoday.roles_value).

    python scripts/test_st_roles.py

Без мережі й без Firestore: лише перетворення.
"""
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv()  # core.utils вимагає змінні середовища вже на імпорті
sys.stdout.reconfigure(encoding="utf-8")

from core.schooltoday import roles_value  # noqa: E402

_fails = 0


def check(label, got, want):
    global _fails
    ok = got == want
    _fails += not ok
    print(f"  [{'OK ' if ok else 'FAIL'}] {label}: {got!r}" + ("" if ok else f"  (очікували {want!r})"))


check("лише student -> порожньо", roles_value({"roles": ["student"]}), "")
check("назви як у панелі, порядок фіксований",
      roles_value({"roles": ["buddy", "student", "scl"]}), "Student Council;Buddy")
check("buddy lead/head", roles_value({"roles": ["buddy_head", "buddy_lead"]}), "Buddy Lead;Buddy Head")
check("gsl передається", roles_value({"roles": ["student", "gsl", "buddy"]}), "Buddy;GSL")
check("boss не передається", roles_value({"roles": ["student", "prefect", "scl", "itt", "boss"]}),
      "Student Council;Prefect;ITT")
check("рядок після правки в Rowy", roles_value({"roles": "student, scl | itt"}), "Student Council;ITT")
check("невідома роль ігнорується", roles_value({"roles": ["teacher", "whatever"]}), "")
check("немає поля", roles_value({}), "")

print("\n✅ Усі перевірки пройдені" if not _fails else f"\n❌ Провалено: {_fails}")
sys.exit(1 if _fails else 0)
