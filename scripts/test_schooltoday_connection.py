# scripts/test_schooltoday_connection.py
"""
Одноразовий діагностичний скрипт для перевірки підключення до SchoolToday API.

Використання (з кореня проєкту, після того як в .env додано реальний
SCHOOL_TODAY_API_BASE_URL / SCHOOL_TODAY_API_KEY):

    python -m scripts.test_schooltoday_connection [pupil_id]

Без аргументу друкує лише список кастомних полів. З аргументом (ID тестового
учня, який дасть розробник SchoolToday) додатково запитує цього учня.
"""
import asyncio
import sys
from dotenv import load_dotenv

load_dotenv()

from core import schooltoday


async def main():
    print("--- Custom Fields (GET /v1/PupilCustomFields) ---")
    fields = await schooltoday.get_custom_fields()
    if not fields:
        print("(порожньо)")
    for f in fields:
        print(f"- {f.get('name')!r} | type={f.get('type')} | required={f.get('isRequired')} | options={f.get('options')}")

    if len(sys.argv) > 1:
        pupil_id = int(sys.argv[1])
        print(f"\n--- Pupil #{pupil_id} (GET /v1/Pupils/{pupil_id}) ---")
        pupil = await schooltoday.get_pupil(pupil_id)
        print(pupil)


if __name__ == "__main__":
    asyncio.run(main())
