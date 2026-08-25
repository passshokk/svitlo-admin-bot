"""Аудит якості даних у Firestore. Нічого не змінює — лише рахує й показує.

    python -m scripts.audit_data_quality
    python -m scripts.audit_data_quality --show 30   # більше прикладів на категорію
"""
import argparse
import asyncio
import collections
import difflib
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv()

from core.database import db  # noqa: E402
from core.utils import normalize_phone  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

CYRILLIC = re.compile(r"[А-Яа-яЁёІіЇїЄєҐґ]")
LATIN = re.compile(r"[A-Za-z]")

# Закінчення, що майже однозначно вказують на прізвище
SURNAME_ENDINGS = (
    "енко", "ко", "ук", "юк", "чук", "ський", "ська", "цький", "цька",
    "ов", "ова", "ев", "єва", "ин", "іна", "ина", "их", "ій", "ая",
    "ак", "як", "ань", "аш", "ба", "да", "ло", "ра", "ша", "ський",
)
# Закінчення по батькові. `-ич` сюди НЕ входить: на нього закінчується безліч
# звичайних прізвищ — Химич, Речич, Бабич, Назаревич, Левкович, Іцкович.
# Через нього перша версія правила дала 37 хибних спрацювань замість трьох.
PATRONYMIC_ENDINGS = ("івна", "ївна", "овна", "евна")

# Українські імена. Словник має бути широким: із вузьким половина записів
# потрапляє в «неоднозначно» просто тому, що імені немає в переліку.
GIVEN_NAMES = {
    # жіночі
    "олена", "оксана", "наталія", "наталя", "тетяна", "ірина", "світлана", "ольга",
    "юлія", "юлия", "марія", "мария", "анна", "ганна", "людмила", "вікторія", "катерина",
    "алла", "валентина", "лариса", "інна", "надія", "любов", "галина", "марина",
    "мар'яна", "марʼяна", "мар’яна", "маряна", "мар'ям", "олександра", "аліна", "діана",
    "евеліна", "неля", "лілія", "жанна", "яна", "анастасія", "вероніка", "софія",
    "христина", "мирослава", "зоряна", "уляна", "станіслава", "ангеліна", "альона",
    "маргарита", "валерія", "аліса", "дарина", "дарʼя", "дар'я", "дарія", "руслана",
    "ярина", "юліанна", "юліана", "оляна", "леся", "зоя", "віра", "ніна", "раїса",
    "тамара", "лідія", "емілія", "кароліна", "поліна", "злата", "мілана", "камілла",
    "каміла", "богдана", "соломія", "олеся", "яніна", "інеса", "аделіна", "єлизавета",
    "елизавета", "єва", "варвара", "ксенія", "кристина", "крістіна", "снєжана",
    "сніжана", "лілія", "азалія", "роксолана", "орися", "христя", "катя", "таня",
    "оля", "іра", "юля", "настя", "лєна", "маша", "даша", "саша", "віта", "ліна",
    "лада", "нонна", "неоніла", "мотрона", "агнеса", "єлєна", "альбіна", "ілона",
    "анжела", "анжеліка", "тетьяна", "натали", "антоніна", "фаїна", "єлєна",
    # чоловічі
    "олексій", "олександр", "сергій", "андрій", "володимир", "ігор", "юрій",
    "михайло", "дмитро", "роман", "тарас", "богдан", "віталій", "євген", "артем",
    "максим", "павло", "петро", "василь", "микола", "іван", "денис", "костянтин",
    "леонід", "анатолій", "валерій", "григорій", "степан", "остап", "назар",
    "ярослав", "святослав", "мирослав", "ростислав", "владислав", "вадим", "едуард",
    "руслан", "тимур", "марко", "матвій", "захар", "лев", "давид", "данило",
    "арсен", "арсеній", "нікіта", "микита", "єгор", "єгор", "антон", "борис",
    "віктор", "геннадій", "олег", "стас", "станіслав", "тимофій", "макар", "ілля",
    "фелікс", "родіон", "юліан", "адам", "марк", "оксен", "любомир", "остап",
}


def issues_for_name(value: str, field: str, latin_expected: bool) -> list[str]:
    found = []
    if value != value.strip():
        found.append(f"{field}: пробіли по краях")
    core = value.strip()
    if not core:
        found.append(f"{field}: порожнє")
        return found
    if "  " in core:
        found.append(f"{field}: подвійні пробіли")
    if core.isupper() and len(core) > 2:
        found.append(f"{field}: ВЕРХНІЙ регістр")
    elif core.islower():
        found.append(f"{field}: нижній регістр")
    elif core != core.title() and " " not in core and "-" not in core and "'" not in core:
        found.append(f"{field}: не Title Case")
    if latin_expected and CYRILLIC.search(core):
        found.append(f"{field}: кирилиця там, де очікується латиниця")
    if not latin_expected and LATIN.search(core) and not CYRILLIC.search(core):
        found.append(f"{field}: латиниця там, де очікується кирилиця")
    if re.search(r"\d", core):
        found.append(f"{field}: містить цифри")
    return found


# Спрощена транслітерація для звірки латинських написань зі словником імен.
# Точність тут не потрібна — треба лише, щоб 'Olena' і 'Олена' зійшлись.
_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "h", "ґ": "g", "д": "d", "е": "e", "є": "ie",
    "ж": "zh", "з": "z", "и": "y", "і": "i", "ї": "i", "й": "i", "к": "k", "л": "l",
    "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch", "ь": "",
    "ю": "iu", "я": "ia", "'": "", "ʼ": "", "’": "",
}
# Написання, які транслітерація не зведе: Ганна/Hanna/Anna, Юлія/Yulia/Julia тощо
LATIN_GIVEN_EXTRA = {
    "anna", "hanna", "ganna", "yulia", "julia", "yuliia", "iuliia", "olena", "elena",
    "helena", "maryna", "marina", "mariana", "marianna", "oksana", "oxana", "iryna",
    "irina", "svitlana", "svetlana", "olha", "olga", "nataliia", "natalia", "nataliya",
    "tetiana", "tetyana", "tatiana", "kateryna", "katerina", "viktoriia", "victoria",
    "viktoria", "liudmyla", "ludmila", "halyna", "galina", "alla", "larysa", "larisa",
    "nadiia", "nadia", "yana", "diana", "alina", "daria", "darya", "dariia", "sofiia",
    "sofia", "anastasiia", "anastasia", "veronika", "polina", "zlata", "milana",
    "bohdana", "solomiia", "olesia", "ksenia", "kseniia", "kristina", "khrystyna",
    "yelyzaveta", "elizaveta", "eva", "yeva", "varvara", "valeriia", "valeria",
    "oleksandr", "alexander", "oleksandra", "alexandra", "andrii", "andriy", "andrey",
    "serhii", "sergey", "sergii", "volodymyr", "vladimir", "ihor", "igor", "yurii",
    "yuriy", "mykhailo", "mikhail", "dmytro", "dmitry", "roman", "taras", "bohdan",
    "vitalii", "vitaly", "yevhen", "evgeny", "artem", "maksym", "maxim", "pavlo",
    "petro", "vasyl", "mykola", "nikolay", "ivan", "denys", "denis", "leonid",
    "artur", "arthur", "ruslan", "ruslana", "timur", "tymur", "marko", "mark",
    "nazar", "yaroslav", "yaroslava", "vladyslav", "vadym", "oleh", "oleg", "anton",
    "viktor", "victor", "stanislav", "illia", "danylo", "daniel", "matvii", "zakhar",
}


def _translit(word: str) -> str:
    return "".join(_TRANSLIT.get(c, c) for c in word.strip().lower())


LATIN_GIVEN = {_translit(n) for n in GIVEN_NAMES} | LATIN_GIVEN_EXTRA


# Категорії, які ми свідомо прийняли й не вважаємо дефектом. Без цього списку
# аудит показує 244 «проблеми», з яких справжніх чотири — і його перестають читати.
ACCEPTED = {
    "parentFirstName: латиниця там, де очікується кирилиця",
    "parentLastName: латиниця там, де очікується кирилиця",
    "parentFirstName: порожнє",
    "parentLastName: порожнє",
    "ПІБ батька: неповне",
    "ПІБ батька: можливо по батькові",
    "ПІБ батька: неоднозначно",
}

ACCEPTED_WHY = {
    "латиниця": "батьки самі так записались — це написання, а не помилка",
    "порожнє": "лишилось після прибирання по батькові; справжнього значення ми не знаємо",
    "неповне": "те саме — одна половина ПІБ відсутня в джерелі",
    "можливо по батькові": "перевірено вручну: це прізвища на -ович, не по батькові",
    "неоднозначно": "перевірено вручну; частина підтверджена прізвищем дитини",
}


def surname_matches_pupil(parent_last: str, pupil_last: str) -> bool:
    """Чи збігається прізвище батька з прізвищем дитини.

    Найсильніший сигнал правильного порядку полів: батько записаний кирилицею,
    дитина латиницею, тож звіряємо транслітерації нестрого.
    """
    a, b = _translit(parent_last), (pupil_last or "").strip().lower()
    if not a or not b:
        return False
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.75


def looks_like_surname(word: str) -> bool:
    w = word.strip().lower()
    return any(w.endswith(e) for e in SURNAME_ENDINGS)


def looks_like_given(word: str) -> bool:
    w = word.strip().lower()
    return w in GIVEN_NAMES or w in LATIN_GIVEN or _translit(w) in LATIN_GIVEN


def classify_parent_name(first: str, last: str) -> tuple[str, str]:
    """Повертає (категорія, пояснення)."""
    f, l = first.strip(), last.strip()
    if not f or not l:
        return "неповне", "порожнє поле"

    fl, ll = f.lower(), l.lower()
    # -івна/-ївна/-овна/-евна не буває нічим іншим, крім по батькові.
    # -ович виносимо окремо: на нього закінчуються й прізвища (Попович, Ігнатович).
    if any(ll.endswith(e) for e in PATRONYMIC_ENDINGS):
        return "по батькові у прізвищі", f"{l!r} — це по батькові"
    if any(fl.endswith(e) for e in PATRONYMIC_ENDINGS):
        return "по батькові в імені", f"{f!r} — це по батькові"
    if ll.endswith(("ович", "йович")) and looks_like_given(f):
        return "можливо по батькові", f"{l!r} — по батькові або прізвище"

    f_given, l_given = looks_like_given(f), looks_like_given(l)
    f_surname, l_surname = looks_like_surname(f), looks_like_surname(l)

    if l_given and not f_given and (f_surname or not l_surname):
        return "переплутано", f"{l!r} — ім'я, {f!r} — прізвище"
    if f_given and not l_given:
        return "правильно", ""
    if f_given and l_given:
        return "неоднозначно", "обидва схожі на імена"
    if not f_given and not l_given:
        if f_surname and not l_surname:
            return "неоднозначно", f"{f!r} схоже на прізвище, {l!r} невідоме"
        return "неоднозначно", "жодне не впізнано"
    return "неоднозначно", ""


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", type=int, default=12)
    args = ap.parse_args()

    docs = []
    async for snap in db.collection("Svitlo").stream():
        docs.append((snap.id, snap.to_dict() or {}))
    print(f"Документів у Svitlo: {len(docs)}\n")

    buckets: dict[str, list] = collections.defaultdict(list)
    confirmed_by_pupil: list[str] = []

    for doc_id, d in docs:
        for field, latin in (("firstName", True), ("lastName", True)):
            for issue in issues_for_name(d.get(field) or "", field, latin):
                buckets[issue].append((doc_id, repr(d.get(field))))

        for field in ("parentFirstName", "parentLastName"):
            for issue in issues_for_name(d.get(field) or "", field, False):
                if "порожнє" in issue and not (d.get("parentFirstName") or d.get("parentLastName")):
                    continue
                buckets[issue].append((doc_id, repr(d.get(field))))

        cat, why = classify_parent_name(d.get("parentFirstName") or "",
                                        d.get("parentLastName") or "")
        # Збіг прізвища батька з прізвищем дитини знімає будь-яку неоднозначність
        if cat == "неоднозначно" and surname_matches_pupil(
                d.get("parentLastName") or "", d.get("lastName") or ""):
            cat = "правильно"
            confirmed_by_pupil.append(doc_id)
        if cat != "правильно":
            buckets[f"ПІБ батька: {cat}"].append(
                (doc_id, f"{d.get('parentFirstName')!r} {d.get('parentLastName')!r}  {why}"))

        for field in ("email", "parentEmail"):
            val = d.get(field) or ""
            if val != val.strip():
                buckets[f"{field}: пробіли"].append((doc_id, repr(val)))
            if val and not re.match(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$", val.strip()):
                buckets[f"{field}: підозрілий формат"].append((doc_id, repr(val)))
            domain = val.strip().rsplit("@", 1)[-1].lower() if "@" in val else ""
            if domain in ("gmail.con", "gmail.cim", "gmail.co", "gmai.com", "gmial.com"):
                buckets[f"{field}: помилка домену"].append((doc_id, repr(val)))

        phone = d.get("parentPhone") or ""
        if phone and normalize_phone(phone) != phone:
            buckets["parentPhone: не канонічний E.164"].append((doc_id, repr(phone)))

        nick = d.get("telegramUsername") or ""
        if nick and not nick.startswith("@"):
            buckets["telegramUsername: без @"].append((doc_id, repr(nick)))

        for field in ("city", "country"):
            val = d.get(field) or ""
            if val and val != val.strip().title():
                buckets[f"{field}: регістр або пробіли"].append((doc_id, repr(val)))

        if not d.get("ageGroup"):
            buckets["ageGroup: порожній"].append((doc_id, ""))
        if not d.get("email"):
            buckets["email: порожній"].append((doc_id, ""))

    defects = {k: v for k, v in buckets.items() if k not in ACCEPTED}
    accepted = {k: v for k, v in buckets.items() if k in ACCEPTED}

    print("=" * 74)
    print("ДЕФЕКТИ — ПОТРЕБУЮТЬ ДІЇ")
    print("=" * 74)
    if not defects:
        print("\n  Немає.")
    for issue, items in sorted(defects.items(), key=lambda kv: -len(kv[1])):
        print(f"\n{len(items):>5}  {issue}")
        for doc_id, sample in items[:args.show]:
            print(f"          {doc_id}  {sample}")
        if len(items) > args.show:
            print(f"          … ще {len(items) - args.show}")

    print("\n" + "=" * 74)
    print("ПРИЙНЯТО — ВІДОМИЙ І ПОГОДЖЕНИЙ СТАН")
    print("=" * 74)
    for issue, items in sorted(accepted.items(), key=lambda kv: -len(kv[1])):
        why = next((v for k, v in ACCEPTED_WHY.items() if k in issue), "")
        print(f"{len(items):>5}  {issue}")
        if why:
            print(f"          {why}")
    if confirmed_by_pupil:
        print(f"{len(confirmed_by_pupil):>5}  підтверджено збігом із прізвищем дитини")
        print("          порядок полів правильний, звірка автоматична")

    print("\n" + "=" * 74)
    affected = {doc_id for items in defects.values() for doc_id, _ in items}
    print(f"Дефектів: {sum(len(v) for v in defects.values())} у {len(affected)} документах із {len(docs)}")
    print(f"Прийнятого: {sum(len(v) for v in accepted.values())}")
    print("\nЯкщо категорія з'явилась у «дефектах» уперше — або це справжня проблема,")
    print("або її треба свідомо додати в ACCEPTED з поясненням чому.")


if __name__ == "__main__":
    asyncio.run(main())
