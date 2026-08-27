"""Одноразова чистка: прибрати провідний '@' з кастомного поля
«Telegram Nickname» на всіх картках учнів у SchoolToday.

Це НЕ те саме, що sync_to_schooltoday.py: той синхронізує лише те, що зараз
є у Firestore, і свідомо не займає порожні значення. Тут навпаки — беремо
поточне значення прямо з ШС (незалежно від Firestore) і просто ріжемо
провідний '@', якщо він є. Стосується і карток без прив'язки до Firestore
(легасі, isHidden), яких sync_to_schooltoday взагалі не бачить.

    python -m scripts.strip_nickname_at            # показати, що зміниться
    python -m scripts.strip_nickname_at --apply
"""
import argparse
import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv()
sys.stdout.reconfigure(encoding="utf-8")

from core import schooltoday as st  # noqa: E402

FIELD_NAME = "Telegram Nickname"


def strip_at(custom_data: list[dict]) -> tuple[list[dict], str, str] | None:
    """Повертає (нова customData, старе значення, нове значення) якщо є що
    міняти, інакше None. Правимо КОЖЕН запис з таким іменем — на випадок
    дублікатів (їх зараз немає, але про всяк випадок)."""
    changed = False
    old_value = new_value = ""
    updated = []
    for entry in custom_data:
        if entry.get("name") == FIELD_NAME and (entry.get("value") or "").startswith("@"):
            old_value = entry.get("value") or ""
            new_value = old_value.lstrip("@")
            updated.append({**entry, "value": new_value})
            changed = True
        else:
            updated.append(entry)
    return (updated, old_value, new_value) if changed else None


async def main(argv: list[str] | None = None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)

    pupils = await st.list_pupils()
    print(f"Учнів у ШС: {len(pupils)}")

    jobs = []
    for pupil in pupils:
        result = strip_at(pupil.get("customData") or [])
        if result:
            new_custom, old_value, new_value = result
            jobs.append((pupil["id"], new_custom, old_value, new_value,
                        pupil.get("firstName"), pupil.get("lastName")))

    print(f"Карток зі знайденим '@': {len(jobs)}\n")
    for pupil_id, _, old_value, new_value, first, last in jobs[:15]:
        print(f"  {first} {last}: {old_value!r} → {new_value!r}   [#{pupil_id}]")
    if len(jobs) > 15:
        print(f"  … ще {len(jobs) - 15}")

    if not args.apply:
        print("\nПробний прогін. Щоб застосувати — додай --apply")
        return

    print("\nОновлюю…")
    errors = []
    for index, (pupil_id, new_custom, *_rest) in enumerate(jobs, 1):
        try:
            await st.update_pupil(pupil_id, {"customData": new_custom})
        except st.STError as exc:
            errors.append((pupil_id, exc))
        if index % 100 == 0:
            print(f"  {index}/{len(jobs)}")
    print(f"  {len(jobs)}/{len(jobs)}")

    if errors:
        print(f"\n⚠ ПОМИЛОК: {len(errors)}")
        for pupil_id, exc in errors[:20]:
            print(f"  #{pupil_id}: {exc.status} {exc.codes} {exc.keys}")
    else:
        print("\nПомилок немає.")


if __name__ == "__main__":
    asyncio.run(main())
