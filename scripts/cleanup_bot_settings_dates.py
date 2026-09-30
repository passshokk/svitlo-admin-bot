"""Прибирає з Config/bot_settings ручні дати, які тепер бере календар.

`currentSemester`, `termStartDate`, `inductionStartDate`,
`nextRegistrationDate`, `registrationOpen` — з 30.09.2026 бот і панель їх
не читають: семестр, дати старту й відкриття реєстрації виводяться з
Config/academic_calendar (core/registration.py). Поля, що лишились у
документі, лише вводять в оману: їх правлять у консолі, а нічого не
змінюється.

    python -m scripts.cleanup_bot_settings_dates           # показати, що буде видалено
    python -m scripts.cleanup_bot_settings_dates --apply   # видалити

🟡 з --apply видаляє лише ці п'ять полів одного документа; решту (testers,
registrationOverride тощо) не чіпає. Значення друкуються перед видаленням.
"""
import argparse
import asyncio
import sys

from dotenv import load_dotenv

load_dotenv()

sys.stdout.reconfigure(encoding="utf-8")

from google.cloud import firestore  # noqa: E402

from core.database import db  # noqa: E402

FIELDS = ("currentSemester", "termStartDate", "inductionStartDate",
          "nextRegistrationDate", "registrationOpen")


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    ref = db.collection("Config").document("bot_settings")
    data = (await ref.get()).to_dict() or {}
    present = {field: data[field] for field in FIELDS if field in data}
    if not present:
        print("Нічого прибирати — полів уже немає.")
        return 0
    for field, value in present.items():
        print(f"  {field}: {value!r}")
    if not args.apply:
        print("\nПрев'ю. Щоб видалити: python -m scripts.cleanup_bot_settings_dates --apply")
        return 0
    await ref.update({field: firestore.DELETE_FIELD for field in present})
    print(f"\n🟡 Видалено {len(present)} полів з Config/bot_settings")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
