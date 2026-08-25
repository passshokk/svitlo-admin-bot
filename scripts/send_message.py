# scripts/send_message.py
"""
Ручна відправка одного повідомлення конкретному юзеру за Telegram ID.
Корисно, коли треба вручну перезакинути повідомлення (тестерам, після бага тощо).

Використання (з кореня проєкту, коли в .env є реальний BOT_TOKEN):

    python -m scripts.send_message 123456789 "Текст повідомлення"
    python -m scripts.send_message 123456789 --file message.txt
    python -m scripts.send_message 123456789 "Текст <b>з HTML</b>"
    python -m scripts.send_message 123456789 "Текст без розмітки" --plain
    python -m scripts.send_message 123456789 "Текст" -b "Перейти|https://t.me/svitloschool"
    python -m scripts.send_message 123456789 "Текст" -b "Так|confirm_yes" -b "Ні|confirm_no"

Якщо текст не передано ані аргументом, ані через --file — скрипт зчитає його
зі stdin (Ctrl+Z, Enter на Windows / Ctrl+D на Unix, щоб завершити ввід).

Кнопки (-b/--button, можна кілька разів — кожна своїм рядком) задаються у
форматі "Текст|DATA": DATA що починається з http(s):// стає посиланням (url),
інакше — callback_data.
"""
import argparse
import asyncio
import sys
from dotenv import load_dotenv

load_dotenv()
sys.stdout.reconfigure(encoding="utf-8")

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from core.bot_init import bot


def _build_markup(button_specs: list[str]) -> InlineKeyboardMarkup | None:
    if not button_specs:
        return None
    rows = []
    for spec in button_specs:
        if "|" not in spec:
            raise SystemExit(f"Некоректний формат кнопки: {spec!r}, очікується \"Текст|DATA\"")
        text, data = (part.strip() for part in spec.split("|", 1))
        if data.startswith("http://") or data.startswith("https://"):
            rows.append([InlineKeyboardButton(text=text, url=data)])
        else:
            rows.append([InlineKeyboardButton(text=text, callback_data=data)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _send_once(telegram_id: int, text: str, plain: bool, markup: InlineKeyboardMarkup | None) -> None:
    while True:
        try:
            await bot.send_message(
                chat_id=telegram_id,
                text=text,
                parse_mode=None if plain else "HTML",
                reply_markup=markup,
            )
            print(f"✅ Надіслано юзеру {telegram_id}")
            return
        except TelegramForbiddenError:
            print(f"⛔ Юзер {telegram_id} заблокував бота (або вийшов з чату) — не доставлено")
            return
        except TelegramBadRequest as e:
            print(f"❌ Telegram відхилив запит: {e}")
            return
        except TelegramRetryAfter as e:
            print(f"⏳ Flood control, повторюю через {e.retry_after}с...")
            await asyncio.sleep(e.retry_after)


async def _run(telegram_id: int, text: str, plain: bool, markup: InlineKeyboardMarkup | None) -> None:
    try:
        await _send_once(telegram_id, text, plain, markup)
    finally:
        await bot.session.close()


def _read_text(args: argparse.Namespace) -> str:
    if args.file:
        with open(args.file, encoding="utf-8") as f:
            return f.read()
    if args.text:
        return args.text
    print("Введи текст повідомлення, потім Ctrl+Z і Enter (Windows) / Ctrl+D (Unix):")
    return sys.stdin.read()


def main() -> None:
    parser = argparse.ArgumentParser(description="Надіслати повідомлення конкретному юзеру за Telegram ID")
    parser.add_argument("telegram_id", type=int, help="Telegram ID отримувача")
    parser.add_argument("text", nargs="?", help="Текст повідомлення (або використай --file чи stdin)")
    parser.add_argument("--file", help="Шлях до файлу з текстом повідомлення (UTF-8)")
    parser.add_argument("--plain", action="store_true", help="Без HTML-розмітки")
    parser.add_argument(
        "-b", "--button", action="append", default=[], metavar="ТЕКСТ|DATA",
        help="Додати inline-кнопку (можна кілька разів, кожна своїм рядком). "
             "DATA що починається з http(s):// — посилання, інакше — callback_data.",
    )
    args = parser.parse_args()

    text = _read_text(args).strip()
    if not text:
        parser.error("Текст повідомлення не може бути пустим")

    markup = _build_markup(args.button)
    asyncio.run(_run(args.telegram_id, text, args.plain, markup))


if __name__ == "__main__":
    main()
