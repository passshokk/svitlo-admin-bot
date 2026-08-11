# scripts/test_schooltoday_connection.py
"""
Діагностичний скрипт для SchoolToday API. Тільки читання — нічого не пише.

Використання (з кореня проєкту, коли в .env є реальний SCHOOL_TODAY_API_KEY):

    python -m scripts.test_schooltoday_connection            # кастомні поля + зведення по базі
    python -m scripts.test_schooltoday_connection 930        # + повна картка учня #930
    python -m scripts.test_schooltoday_connection 930 --raw  # без маскування ПД

За замовчуванням персональні дані (ім'я, дата народження, адреса) маскуються,
щоб їх можна було безпечно копіювати в чат/тікет.
"""
import asyncio
import json
import sys
from collections import Counter
from dotenv import load_dotenv

load_dotenv()

# Консоль Windows (cp866/cp1251) калічить українські назви полів — форсуємо UTF-8
sys.stdout.reconfigure(encoding="utf-8")

from core import schooltoday

MASKED_FIELDS = {"firstName", "lastName", "patronymic", "fullName", "birthday", "address"}


def _mask(pupil: dict, raw: bool) -> dict:
    if raw:
        return pupil
    return {k: ("<masked>" if k in MASKED_FIELDS and v else v) for k, v in pupil.items()}


async def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    raw = "--raw" in sys.argv

    print("=== Кастомні поля (GET /v1/PupilCustomFields) ===")
    for f in await schooltoday.get_custom_fields():
        print(f"  id={f['id']:<4} type={f['type']} required={str(f['isRequired']):<5} "
              f"name={f['name']!r} options={f['options']}")

    print("\n=== Зведення по базі (GET /v1/Pupils) ===")
    pupils = await schooltoday.get_pupils()
    print(f"  Всього учнів: {len(pupils)}")
    print(f"  Поля моделі: {sorted(pupils[0].keys())}")

    for field in ("className", "pupilTypeName", "gender"):
        counts = Counter(p.get(field) for p in pupils)
        print(f"  {field}: {dict(counts)}")

    used = Counter(c["name"] for p in pupils for c in (p.get("customData") or []))
    print(f"  Заповненість кастомних полів: {dict(used)}")

    if args:
        pupil_id = int(args[0])
        print(f"\n=== Картка учня #{pupil_id} (GET /v1/Pupils/{pupil_id}) ===")
        pupil = await schooltoday.get_pupil(pupil_id)
        custom = pupil.pop("customData", None)
        print(json.dumps(_mask(pupil, raw), ensure_ascii=False, indent=2))
        print("  customData:")
        for c in custom or []:
            print(f"    {c['name']!r} = {c['value']!r}")


if __name__ == "__main__":
    asyncio.run(main())
