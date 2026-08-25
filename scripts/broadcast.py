# scripts/broadcast.py
"""
Розсилка повідомлення групі юзерів із колекції Firestore `Svitlo`, відфільтрованих
за будь-якою комбінацією полів профілю.

Використання (з кореня проєкту, коли в .env є реальний BOT_TOKEN):

    # 1. Спершу завжди прогнати БЕЗ --yes — це тільки покаже кого зачепить фільтр
    python -m scripts.broadcast --house Caledonia --text "Привіт, Каледоніє!"

    # 2. Коли впевнений(-а) у виборці — додай --yes, щоб реально відправити
    python -m scripts.broadcast --house Caledonia --text "Привіт, Каледоніє!" --yes

Приклади фільтрів (комбінуються через AND, --role — через OR всередині себе):
    --age-group older
    --gender Female
    --house Hibernia
    --role buddy prefect          # будь-хто з роллю buddy АБО prefect
    --stage lead
    --has-group-access / --no-has-group-access
    --displaced / --no-displaced
    --country Україна
    --city Львів

Текст — аргументом --text, файлом --file або stdin. Підтримується HTML (як і в боті),
--plain вимикає розмітку. --limit обмежує кількість реальних відправок (для тестового
прогону на підмножині). --rate — повідомлень на секунду (дефолт 20, з запасом від
ліміту Telegram ~30/с).
"""
import argparse
import asyncio
import sys
from dotenv import load_dotenv

load_dotenv()
sys.stdout.reconfigure(encoding="utf-8")

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from core.bot_init import bot
from core.database import db as firestore_client
from core import config as cfg

COLLECTION = "Svitlo"


def _bool_str(value: bool) -> str:
    return "так" if value else "ні"


def _matches(data: dict, args: argparse.Namespace) -> bool:
    if not data.get("telegramId"):
        return False
    if args.age_group and data.get("ageGroup") != args.age_group:
        return False
    if args.gender and data.get("gender") != args.gender:
        return False
    if args.house and data.get("house") != args.house:
        return False
    if args.role and not set(data.get("roles") or []) & set(args.role):
        return False
    if args.stage and data.get("stage") != args.stage:
        return False
    if args.has_group_access is not None and bool(data.get("hasGroupAccess")) != args.has_group_access:
        return False
    if args.displaced is not None and bool(data.get("isDisplaced")) != args.displaced:
        return False
    if args.country and data.get("country", "").strip().lower() != args.country.strip().lower():
        return False
    if args.city and data.get("city", "").strip().lower() != args.city.strip().lower():
        return False
    return True


async def _fetch_matching(args: argparse.Namespace) -> list[tuple[str, dict]]:
    matched = []
    async for doc in firestore_client.collection(COLLECTION).stream():
        data = doc.to_dict()
        if _matches(data, args):
            matched.append((doc.id, data))
    return matched


def _read_text(args: argparse.Namespace) -> str:
    if args.file:
        with open(args.file, encoding="utf-8") as f:
            return f.read()
    if args.text:
        return args.text
    print("Введи текст повідомлення, потім Ctrl+Z і Enter (Windows) / Ctrl+D (Unix):")
    return sys.stdin.read()


async def _send_one(telegram_id: int, text: str, plain: bool) -> str:
    """Повертає 'sent' / 'blocked' / 'failed'."""
    while True:
        try:
            await bot.send_message(
                chat_id=telegram_id,
                text=text,
                parse_mode=None if plain else "HTML",
            )
            return "sent"
        except TelegramForbiddenError:
            return "blocked"
        except TelegramBadRequest as e:
            print(f"  ❌ {telegram_id}: {e}")
            return "failed"
        except TelegramRetryAfter as e:
            print(f"  ⏳ Flood control, чекаю {e.retry_after}с...")
            await asyncio.sleep(e.retry_after)


async def _broadcast(recipients: list[tuple[str, dict]], text: str, plain: bool, rate: float, limit: int | None) -> None:
    if limit:
        recipients = recipients[:limit]

    delay = 1 / rate if rate > 0 else 0
    counts = {"sent": 0, "blocked": 0, "failed": 0}

    try:
        for doc_id, data in recipients:
            result = await _send_one(int(data["telegramId"]), text, plain)
            counts[result] += 1
            name = f"{data.get('firstName', '')} {data.get('lastName', '')}".strip() or doc_id
            print(f"  [{result}] {name} ({data['telegramId']})")
            if delay:
                await asyncio.sleep(delay)
    finally:
        await bot.session.close()

    print(
        f"\nГотово: надіслано {counts['sent']}, заблокували бота {counts['blocked']}, "
        f"помилок {counts['failed']} (з {len(recipients)})"
    )


def _print_preview(recipients: list[tuple[str, dict]]) -> None:
    print(f"Під фільтр підпадає {len(recipients)} юзер(ів):")
    for doc_id, data in recipients[:30]:
        name = f"{data.get('firstName', '')} {data.get('lastName', '')}".strip() or "(без імені)"
        print(f"  - {name} | tg={data.get('telegramId')} | house={data.get('house')} | "
              f"ageGroup={data.get('ageGroup')} | roles={data.get('roles')}")
    if len(recipients) > 30:
        print(f"  ... і ще {len(recipients) - 30}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Розсилка повідомлення юзерам Svitlo, відфільтрованим за даними профілю",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--text", help="Текст повідомлення")
    parser.add_argument("--file", help="Шлях до файлу з текстом повідомлення (UTF-8)")
    parser.add_argument("--plain", action="store_true", help="Без HTML-розмітки")

    parser.add_argument("--age-group", choices=sorted(cfg.GROUPS_MAPPING.keys()))
    parser.add_argument("--gender", choices=["Male", "Female", "Unspecified"])
    parser.add_argument("--house", choices=sorted(set(cfg.HOUSE_CHATS.keys()) | {"Newbie"}))
    parser.add_argument("--role", nargs="+", choices=sorted(cfg.ROLE_MAP.keys()),
                         help="Одна чи декілька ролей — співпадіння за АБО")
    parser.add_argument("--stage", help="Точна назва stage (напр. lead)")
    parser.add_argument("--has-group-access", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--displaced", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--country")
    parser.add_argument("--city")

    parser.add_argument("--rate", type=float, default=20, help="Повідомлень на секунду (дефолт 20)")
    parser.add_argument("--limit", type=int, help="Максимум реальних відправок (для тестового прогону)")
    parser.add_argument("--yes", action="store_true", help="Реально відправити. Без цього прапорця — лише прев'ю вибірки")
    args = parser.parse_args()

    text = _read_text(args).strip()
    if not text:
        parser.error("Текст повідомлення не може бути пустим")

    recipients = asyncio.run(_fetch_matching(args))
    _print_preview(recipients)

    if not recipients:
        return

    if not args.yes:
        print("\n(Це прев'ю. Додай --yes, щоб реально відправити повідомлення цій вибірці.)")
        return

    confirm = input(f"\nТочно відправити {min(args.limit or len(recipients), len(recipients))} юзерам? (yes/no): ")
    if confirm.strip().lower() not in ("yes", "y", "так"):
        print("Скасовано")
        return

    asyncio.run(_broadcast(recipients, text, args.plain, args.rate, args.limit))


if __name__ == "__main__":
    main()
