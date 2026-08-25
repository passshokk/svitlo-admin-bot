"""Чистка даних у Firestore. За замовчуванням нічого не пише.

    python -m scripts.fix_data_quality            # показати всі зміни
    python -m scripts.fix_data_quality --apply    # застосувати

Три проходи:
  1. механічний  — регістр, пробіли, апострофи, гомогліфи; правила детерміновані
  2. евристичний — перестановка ПІБ батьків там, де класифікатор впевнений
  3. ручний      — 57 випадків, розібраних поіменно; таблиця нижче

Пошти з помилками доменів не чіпаємо: це логін, і правка може відрізати людину
від акаунта. Вони йдуть окремим списком для куратора.
"""
import argparse
import asyncio
import collections
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv()

from core.database import db  # noqa: E402
from scripts.audit_data_quality import classify_parent_name  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

BATCH_SIZE = 400

# Кириличні літери, візуально невідрізнимі від латинських. У латинських іменах
# вони — сміття: 'Andriі' має кириличну і, через що ім'я не збігається саме з собою.
HOMOGLYPHS = str.maketrans({
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O",
    "Р": "P", "С": "C", "Т": "T", "У": "Y", "Х": "X", "І": "I",
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "і": "i",
})
CYRILLIC = re.compile(r"[А-Яа-яЁёІіЇїЄєҐґ]")
LATIN = re.compile(r"[A-Za-z]")

# Рішення, ухвалені вручну після перегляду кожного випадку.
# Ключ — пара (ім'я, прізвище) у нижньому регістрі; значення:
#   "swap" — поля переставлені місцями
#   "keep" — виглядає дивно, але правильно (рідкісне ім'я)
#   (ім'я, прізвище) — явна заміна
#   "report" — даних бракує, автоматично не виправити
MANUAL: dict[tuple[str, str], object] = {}

for _pair in [
    ("крусь", "ірина"), ("зоренко", "євгенія"), ("качур", "віталій"),
    ("макогонов", "валентин"), ("остапів-кузьма", "галина"), ("марочок", "віталіна"),
    ("зінченко", "всеволод"), ("зелінська", "діна"), ("сологуб", "ірина"),
    ("мельник", "ірина"), ("кім", "ірина"), ("кордунова", "евгенія"),
    ("пелек", "любов"), ("хубулава", "лінара"), ("рибка", "катерина"),
    ("коновал", "валерій"), ("азімова", "дільбар"), ("славинский", "сергій"),
    ("лагута", "єлізавета"), ("новосад", "катерина"), ("кордубан", "марина"),
    ("раца", "каріна"), ("міхно", "євгенія"), ("турлюн", "тамара"),
    ("ільків", "олександра"), ("гетьман", "ірина"), ("король", "галина"),
    ("федюшко", "михайлина"), ("лаута", "євгенія"), ("зуб", "сергій"),
]:
    MANUAL[_pair] = "swap"

for _pair in [
    ("таїсія", "галянт"), ("іванна", "залога"), ("зореслава", "дорож"),
    ("елла", "назарчук"), ("ярослава", "орловська"), ("іванна", "стаднійчук"),
    ("елла", "деркач"), ("віталіна", "лисенко"), ("інесса", "мокра"),
    ("віталіна", "боднарюк"), ("в'ячеслав", "кришневський"),
    ("таісія", "добровольська"), ("виктор", "рудник"), ("екатерина", "красан"),
    ("александра", "удовик"), ("natalya", "kravchenko"), ("aleksandr", "tinjajev"),
    ("violetta", "loziuk"), ("usniie", "shevketova"), ("viktoriya", "shuliha"),
]:
    MANUAL[_pair] = "keep"

# Ім'я вклеїлось у прізвище
MANUAL[("ярослава", "ярославаскоробогатько")] = ("Ярослава", "Скоробогатько")
# '(мати)' — примітка, а не прізвище; Кужелєва і є прізвищем
MANUAL[("кужелєва", "(мати)")] = ("", "Кужелєва")

# По батькові замість другої частини ПІБ. Прибираємо його повністю, а те, що
# лишилось, кладемо в правильне поле. Що саме там стоїть — прізвище чи ім'я —
# видно з прізвища дитини: 'Мішина' при учениці Mishyna це прізвище, а 'Ілона'
# при Hataliak — ім'я.
#
# У випадку `surname_only` ім'я лишається невідомим, але ШС не приймає порожнє
# firstName — картка тоді не оновлюється взагалі, разом із externalID. Тому туди
# ставиться плейсхолдер PLACEHOLDER_NAME: у ШС картка читається як
# «Прізвище Мішина», що чесно повідомляє «прізвище відоме, імені немає».
# Ганятись за вісімнадцятьма справжніми іменами вирішили не варто.
PLACEHOLDER_NAME = "Прізвище"
for _pair in [
    ("бондаренко", "леонідівна"), ("братищева", "юріївна"), ("георгієва", "сергіївна"),
    ("германчук", "іванівна"), ("горзов", "володимирівна"), ("гречкіна", "петрівна"),
    ("донець", "федорівна"), ("мішина", "миколаївна"), ("прошина", "петрівна"),
    ("семенович", "вікторівна"), ("семеновська", "василівна"), ("шлеюк", "володимирівна"),
    ("ющик", "дмитрівна"), ("азаренко", "ігорович"), ("печерій", "генадійович"),
    ("рішко", "олексійоіич"),
]:
    MANUAL[_pair] = "surname_only"

for _pair in [("ілона", "орестівна"), ("анна", "ігорівна"),
              ("валерія", "костянтинівна"), ("світлана", "богдановна")]:
    MANUAL[_pair] = "given_only"


def fix_case(value: str) -> str:
    """Регістр правимо лише там, де слово повністю в одному регістрі.

    Змішаний регістр не чіпаємо: 'McDonald' і 'Puzyrkova-Uvarova' правильні,
    а .title() зіпсував би перше.
    """
    s = value.strip()
    if not s or not (s.isupper() or s.islower()):
        return s
    return re.sub(r"[^\s\-']+", lambda m: m.group(0).capitalize(), s.lower())


def fix_mechanical(doc: dict) -> dict:
    """Детерміновані правки. Повертає лише поля, що змінились."""
    patch: dict[str, object] = {}

    for field, latin in (("firstName", True), ("lastName", True),
                         ("parentFirstName", False), ("parentLastName", False)):
        original = doc.get(field) or ""
        value = re.sub(r"\s+", " ", original.strip())
        value = value.replace("ʼ", "'").replace("’", "'")
        value = fix_case(value)
        if latin and LATIN.search(value) and CYRILLIC.search(value):
            value = value.translate(HOMOGLYPHS)
        if latin:
            value = re.sub(r"\d+", "", value).strip()
        if value != original:
            patch[field] = value

    nickname = doc.get("telegramUsername") or ""
    if nickname and not nickname.startswith("@"):
        patch["telegramUsername"] = "@" + nickname.lstrip("@")

    for field in ("city", "country"):
        original = doc.get(field) or ""
        value = re.sub(r"\s+", " ", original.strip())
        if value and value != original:
            patch[field] = value

    return patch


def fix_parent_name(first: str, last: str) -> tuple[dict, str]:
    """Повертає (правки, підстава)."""
    key = (first.strip().lower(), last.strip().lower())
    decision = MANUAL.get(key)

    if decision == "keep":
        return {}, "ручне рішення: правильно"
    if decision == "surname_only":
        return {"parentFirstName": PLACEHOLDER_NAME, "parentLastName": first.strip()}, \
               "ручне рішення: прибрано по батькові, лишилось прізвище"
    if decision == "given_only":
        return {"parentFirstName": first.strip(), "parentLastName": ""}, \
               "ручне рішення: прибрано по батькові, лишилось ім'я"
    if decision == "swap":
        return {"parentFirstName": last.strip(), "parentLastName": first.strip()}, \
               "ручне рішення: переставлено"
    if isinstance(decision, tuple):
        return {"parentFirstName": decision[0], "parentLastName": decision[1]}, \
               "ручне рішення: явна заміна"

    category, _ = classify_parent_name(first, last)
    if category == "переплутано":
        return {"parentFirstName": last.strip(), "parentLastName": first.strip()}, \
               "евристика: переставлено"
    return {}, ""


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--show", type=int, default=15)
    args = ap.parse_args()

    docs = []
    async for snap in db.collection("Svitlo").stream():
        docs.append((snap.id, snap.to_dict() or {}))
    print(f"Документів: {len(docs)}\n")

    changes: list[tuple[str, dict, dict]] = []
    reasons = collections.Counter()
    samples = collections.defaultdict(list)
    to_report = []

    for doc_id, original in docs:
        patch = fix_mechanical(original)
        # Перестановку рахуємо вже на почищених значеннях: інакше 'DARIA'/'SKORA'
        # не збіглися б із таблицею рішень, де ключі в нижньому регістрі.
        cleaned = {**original, **patch}

        name_patch, reason = fix_parent_name(
            cleaned.get("parentFirstName") or "", cleaned.get("parentLastName") or ""
        )
        patch.update(name_patch)

        if not patch:
            continue
        for field in patch:
            reasons[field] += 1
            if len(samples[field]) < args.show:
                samples[field].append((doc_id, original.get(field), patch[field]))
        changes.append((doc_id, patch, original))

    print("=" * 74)
    print("ЗМІНИ ЗА ПОЛЯМИ")
    print("=" * 74)
    for field, count in reasons.most_common():
        print(f"\n{count:>5}  {field}")
        for doc_id, was, now in samples[field]:
            print(f"        {was!r}  →  {now!r}")
        if count > args.show:
            print(f"        … ще {count - args.show}")

    print("\n" + "=" * 74)
    print("НЕ ВИПРАВЛЯЄМО — ПОТРІБНА ЛЮДИНА")
    print("=" * 74)
    print("\nПомилки в поштах (це логін — правити лише свідомо):")
    for doc_id, doc in docs:
        for field in ("email", "parentEmail"):
            value = (doc.get(field) or "").strip()
            if not value:
                continue
            if not re.match(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$", value):
                print(f"    {doc_id}  {field}={value!r}  — некоректний формат")
            elif value.rsplit("@", 1)[-1].lower() in (
                    "gmail.con", "gmai.com", "gmial.com", "gmail.co", "gmail.cim"):
                print(f"    {doc_id}  {field}={value!r}  — одруківка в домені")

    print("\n" + "=" * 74)
    print(f"Документів до зміни: {len(changes)} із {len(docs)}")
    print(f"Полів до зміни: {sum(len(p) for _, p, _ in changes)}")

    if not args.apply:
        print("\nПробний прогін. Щоб застосувати — додай --apply")
        return

    print("\nЗаписую…")
    written = 0
    for start in range(0, len(changes), BATCH_SIZE):
        batch = db.batch()
        for doc_id, patch, _ in changes[start:start + BATCH_SIZE]:
            batch.update(db.collection("Svitlo").document(doc_id), patch)
        await batch.commit()
        written += len(changes[start:start + BATCH_SIZE])
        print(f"  {written}/{len(changes)}")
    print("Готово.")


if __name__ == "__main__":
    asyncio.run(main())
