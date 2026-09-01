"""CLI над `core/age_promotion.py` — вікове переведення учнів younger -> older.

Сама логіка живе в `core/`, бо її ще й викликає owner-панель
(`api/admin_routes.py`), а `scripts/` навмисно не їде в прод-контейнер
(.gcloudignore).

    python -m scripts.promote_by_age                    # прев'ю: кого зачепить
    python -m scripts.promote_by_age --apply            # перевести + синк ШС + сповістити
    python -m scripts.promote_by_age --apply --no-notify
    python -m scripts.promote_by_age --apply --no-sync
    python -m scripts.promote_by_age --limit 5 --apply

🟡 пише у Firestore (`ageGroup`); 🔴 з `--apply` (без `--no-sync`) тягне за
собою синк у бойову базу SchoolToday. Завжди спершу без `--apply` — побачиш
повний список кандидатів.
"""
import argparse
import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv()
sys.stdout.reconfigure(encoding="utf-8")

from core.age_promotion import run  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Вікове переведення учнів younger -> older (кому виповнилось 14)"
    )
    ap.add_argument("--apply", action="store_true",
                    help="Виконати. Без цього прапорця — лише прев'ю вибірки")
    ap.add_argument("--no-notify", action="store_true",
                    help="Не надсилати сповіщення учням у Telegram")
    ap.add_argument("--no-sync", action="store_true",
                    help="Не запускати синк у SchoolToday після переведення")
    ap.add_argument("--limit", type=int,
                    help="Обмежити кількість переведень (тестовий прогін на підмножині)")
    args = ap.parse_args()

    asyncio.run(run(
        apply=args.apply,
        notify=not args.no_notify,
        trigger_sync=not args.no_sync,
        limit=args.limit,
    ))


if __name__ == "__main__":
    main()
