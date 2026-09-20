"""Крок 1 міграції: перенесення активних учнів із SchoolToday у Firestore.

Читає базу ШС, зберігає свіжий знімок і створює документи в колекції `Svitlo`.
ШС при цьому не змінюється — жодного запису туди не йде.

    python -m scripts.backfill_firestore              # тільки показати, що зробить
    python -m scripts.backfill_firestore --apply      # записати у Firestore
    python -m scripts.backfill_firestore --limit 5 --apply

Повторний запуск безпечний: учні, для яких документ уже створено, пропускаються
за полем `stPupilId`.
"""
import argparse
import asyncio
import collections
import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

# Щоб працювало і як `python -m scripts.backfill_firestore`, і як прямий запуск
# файлу: у другому випадку Python кладе в sys.path теку скрипта, а не корінь.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

load_dotenv()

from core import schooltoday as st  # noqa: E402
from core.database import db, generate_svitlo_id, get_kyivtime_now  # noqa: E402
from core.utils import normalize_phone  # noqa: E402
from core.schooltoday import normalize_nickname  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

SNAPSHOT_DIR = Path(r"D:\Zabrik\SvitloSchool\work materials\st_backup")
LEGACY_CSV = Path(r"D:\Zabrik\SvitloSchool\DBs\firestore_export_crmstage.csv")
COLLECTION = "Svitlo"

# Службові та тестові картки у ШС: п'ять «хаусів» зі згенерованими поштами,
# два тестові акаунти й одна тестова картка з роллю. Учнями не є, але лежать
# серед активних — без цього списку потрапили б у кожну статистику.
SKIP_ST_IDS = {
    930,   # «Тестовий учень» Kozak
    1624,  # «Roza Mursaliieva [BUDDY]» — тестова
    1666, 1667, 1668, 1669, 1670,  # Newbie / Hibernia / Albion / Caledonia / Cambria House
    1675,  # «Тест2 Тест2»
}
BATCH_SIZE = 400  # ліміт Firestore — 500 операцій на батч

# Порядок як в опціях кастомного поля «Ролі» у ШС. У Firestore ці ж ролі живуть
# у `roles` малими літерами — саме такі ключі перебирає cfg.ROLE_MAP при
# рендері профілю, тож капс там не показався б узагалі.
ROLE_ORDER = ["SCL", "BUDDY", "PREFECT", "GSL"]
ROLE_MARKERS = set(ROLE_ORDER)

# «Джерело ліда» історично містило семестр зарахування, а не джерело.
#
# Для тих, кого мапа не знає, ставимо ДІАПАЗОН `23-26`, а не колишній
# сентинел `prior_semesters`. Причина одна — сортування: слово сортувалось
# після всіх цифр, тож найстаріші учні опинялись на вершині списку
# семестрів, вище за поточний. Діапазон у тому ж форматі `YY-YY` лягає
# туди, де йому й місце, — перед `25-26_05`.
SEMESTER_MAP = {"5": "25-26_05", "6-26": "25-26_06"}
SEMESTER_LEGACY = "23-26"

GENDER_FROM_ST = {0: "Male", 1: "Female"}
AGE_GROUP_FROM_ST = {"14-18 років": "older", "10-13 років": "younger"}


def split_roles(last_name: str) -> tuple[str, list[str]]:
    """Відділяє мітки ролей від прізвища.

    Знімає лише відомі мітки, а не все після першого слова: інакше складені
    прізвища на кшталт `Ben Ammar` втратили б половину.
    """
    kept, roles = [], []
    for token in re.split(r"\s+", (last_name or "").strip()):
        if not token:
            continue
        bare = token.strip("[](){}").upper()
        if bare in ROLE_MARKERS:
            roles.append(bare)
        else:
            kept.append(token)
    ordered = sorted(set(roles), key=ROLE_ORDER.index)
    return " ".join(kept).strip(), ordered


def custom(pupil: dict, field_name: str) -> str:
    for entry in pupil.get("customData") or []:
        if (entry.get("name") or "").strip() == field_name:
            return (entry.get("value") or "").strip()
    return ""


def parse_birthday(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(hour=12, minute=0, second=0, microsecond=0, tzinfo=timezone.utc)


def age_group_for(pupil: dict, names: dict, birth: datetime | None) -> str:
    explicit = AGE_GROUP_FROM_ST.get(custom(pupil, names["age_group"]))
    if explicit:
        return explicit
    if not birth:
        return ""
    today = datetime.now(timezone.utc)
    age = today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))
    return "older" if 14 <= age <= 18 else "younger" if 10 <= age <= 13 else ""


def merge_roles(pupil: dict, legacy: dict | None) -> tuple[list[str], list[str]]:
    """Підсумкові ролі та ті, що були в старому експорті й зникли.

    Шкільні ролі беремо з прізвищ у ШС — вони на місяць свіжіші за експорт.
    `itt` і `boss` є лише в експорті, тож переносимо їх звідти.
    """
    _, from_surname = split_roles(pupil.get("lastName"))
    school = [r.lower() for r in from_surname]

    legacy_all = {r.strip().lower()
                  for r in ((legacy or {}).get("Roles") or "").split(",") if r.strip()}
    legacy_school = {r for r in legacy_all if r.upper() in ROLE_MARKERS}
    other = sorted(legacy_all - legacy_school - {"student"})

    dropped = sorted(legacy_school - set(school))
    return ["student"] + school + other, dropped


def build_document(pupil: dict, parent: dict | None, legacy: dict | None,
                   names: dict, now: datetime) -> dict:
    last_name, _ = split_roles(pupil.get("lastName"))
    birth = parse_birthday(pupil.get("birthday"))
    address = (pupil.get("address") or "").strip()
    city, _, country = (part.strip() for part in address.partition(","))

    semester_raw = custom(pupil, names["lead_source"])
    roles, _dropped = merge_roles(pupil, legacy)

    # Нікнейм у ШС свіжіший і повніший (181 проти 118), тож експорт — запасний
    nickname = custom(pupil, names["tg_nickname"]) or (legacy or {}).get("Telegram Nickname", "")
    # Telegram ID у ШС порожній у всіх — поле щойно створене, тож джерело лише експорт
    tg_id_raw = (custom(pupil, names["tg_id"])
                 or (legacy or {}).get("Telegram ID", "")).strip()

    return {
        # ⚙️ System & Tracking
        "semester": SEMESTER_MAP.get(semester_raw, SEMESTER_LEGACY),
        "telegramId": int(tg_id_raw) if tg_id_raw.isdigit() else None,
        "telegramUsername": normalize_nickname(nickname),
        "stage": "student",
        "createdAt": now,
        "stageUpdatedAt": now,
        "followupStep": 0,
        # Походження запису: stPupilId буде і в учнів із бота, тож ознакою не є
        "createdVia": "import",
        "stPupilId": pupil["id"],
        "stParentId": parent["id"] if parent else None,

        # 👤 Student Info
        "firstName": (pupil.get("firstName") or "").strip(),
        "lastName": last_name,
        "email": (pupil.get("email") or "").strip().lower(),
        "phone": "",  # у моделі учня ШС телефону немає
        "gender": GENDER_FROM_ST.get(pupil.get("gender"), ""),
        "birthDate": birth,
        "ageGroup": age_group_for(pupil, names, birth),

        # 📍 Location & IDP
        "country": country,
        "city": city,
        "isDisplaced": custom(pupil, names["idp"]) == "Так",
        "displacedRegion": custom(pupil, names["idp_region"]),

        # 👨‍👩‍👧 Parents
        "parentFirstName": (parent.get("firstName") or "").strip() if parent else "",
        "parentLastName": (parent.get("lastName") or "").strip() if parent else "",
        "parentEmail": (parent.get("email") or "").strip().lower() if parent else "",
        "parentPhone": normalize_phone(parent.get("phoneNumber")) or "" if parent else "",

        # 🏥 Health & Marketing
        "leadSource": "",  # справжнє джерело ШС не зберігав
        "hasHealthIssues": custom(pupil, names["health"]) == "Так",
        "healthIssuesDetails": custom(pupil, names["health_details"]),

        # 📚 Rules / 🤖 AI / 🔁 Anti-duplicate
        "rulesMistakes": 0,
        "aiInfo": {},
        "possibleDuplicateId": "",

        # 🔐 Access & Roles
        "hasGroupAccess": (legacy or {}).get("Group Access", "").strip().upper() == "YES",
        "hasHouseAccess": (legacy or {}).get("House Access", "").strip().upper() == "YES",
        "house": (pupil.get("pupilTypeName") or "").strip() or "Newbie",
        # Шкільні ролі живуть тут же, малими літерами — саме такі ключі
        # перебирає cfg.ROLE_MAP при рендері профілю
        "roles": roles,
    }


async def existing_st_ids() -> set[int]:
    found = set()
    async for doc in db.collection(COLLECTION).stream():
        st_id = (doc.to_dict() or {}).get("stPupilId")
        if st_id:
            found.add(st_id)
    return found


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="реально писати у Firestore")
    ap.add_argument("--limit", type=int, help="обмежити кількість учнів")
    ap.add_argument("--from-snapshot", action="store_true",
                    help="взяти дані з останнього збереженого знімка замість запиту до ШС")
    args = ap.parse_args()

    if args.from_snapshot:
        saved = sorted(SNAPSHOT_DIR.glob("schooltoday_snapshot_*.json"))
        if not saved:
            sys.exit("Знімків не знайдено — запусти без --from-snapshot")
        data = json.loads(saved[-1].read_text(encoding="utf-8"))
        pupils = data["pupils"]
        parents = {p["id"]: p for p in data["parents"]}
        print(f"Джерело: знімок {saved[-1].name}")
        names = {alias: data["_meta"]["field_names"][alias]
                 for alias in st.FIELD_IDS} if "field_names" in data.get("_meta", {}) else None
        if names is None:
            names = (await st.get_registry())["field_name"]
    else:
        print("Читаю базу SchoolToday…")
        pupils = await st.list_pupils()
        parents = {p["id"]: p for p in await st.list_parents()}
        names = (await st.get_registry())["field_name"]

        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
        snapshot = SNAPSHOT_DIR / f"schooltoday_snapshot_{stamp}.json"
        snapshot.write_text(json.dumps(
            {"_meta": {"taken_at": datetime.now().isoformat(), "reason": "backfill",
                       "field_names": names},
             "pupils": pupils, "parents": list(parents.values())},
            ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"Знімок збережено: {snapshot.name}")

    legacy_rows = list(csv.DictReader(open(LEGACY_CSV, encoding="utf-8-sig")))
    legacy_by_email = {(r["Email"] or "").strip().lower(): r
                       for r in legacy_rows if (r["Email"] or "").strip()}
    print(f"Старий експорт Firestore: {len(legacy_rows)} рядків")

    all_active = [p for p in pupils if not p.get("isHidden")]
    skipped = [p for p in all_active if p["id"] in SKIP_ST_IDS]
    active = [p for p in all_active if p["id"] not in SKIP_ST_IDS]
    already = await existing_st_ids()
    todo = [p for p in active if p["id"] not in already]
    if args.limit:
        todo = todo[:args.limit]

    st_emails = {(p.get("email") or "").strip().lower() for p in active if p.get("email")}
    orphans = [e for e in legacy_by_email if e not in st_emails]

    print(f"\nучнів у ШС {len(pupils)} · активних {len(all_active)}")
    print(f"службових і тестових пропущено: {len(skipped)}")
    for p in skipped:
        print(f"    #{p['id']:<6} {p.get('fullName')!r}")
    print(f"справжніх активних: {len(active)}")
    print(f"вже у Firestore {len(already)} · до створення {len(todo)}")
    print(f"рядків експорту без пари у ШС: {len(orphans)} — пропускаємо свідомо")

    now = get_kyivtime_now()
    documents, no_legacy, dropped_roles = [], [], []
    for pupil in todo:
        parent_ids = pupil.get("parentIDs") or []
        parent = parents.get(parent_ids[0]) if parent_ids else None
        legacy = legacy_by_email.get((pupil.get("email") or "").strip().lower())
        if legacy is None:
            no_legacy.append(pupil)
        else:
            _, lost = merge_roles(pupil, legacy)
            if lost:
                dropped_roles.append((pupil, legacy, lost))
        documents.append(
            (generate_svitlo_id(), build_document(pupil, parent, legacy, names, now))
        )

    stats = collections.Counter()
    for _, doc in documents:
        stats["з батьком" if doc["stParentId"] else "без батька"] += 1
        stats[f"семестр {doc['semester']}"] += 1
        if len(doc["roles"]) > 1:
            stats["з ролями понад student"] += 1
        if doc["telegramId"]:
            stats["з Telegram ID"] += 1
        if doc["telegramUsername"]:
            stats["з нікнеймом"] += 1
        if doc["hasGroupAccess"]:
            stats["з доступом до групи"] += 1
        if doc["hasHouseAccess"]:
            stats["з доступом до хаусу"] += 1
        if not doc["ageGroup"]:
            stats["⚠ без вікової групи"] += 1
        if not doc["email"]:
            stats["⚠ без пошти"] += 1

    print("\nЗведення:")
    for key, value in sorted(stats.items()):
        print(f"  {value:>5}  {key}")

    print(f"\nАктивних у ШС без пари в експорті: {len(no_legacy)} — створюємо без "
          f"Telegram ID і доступів")
    for pupil in no_legacy:
        print(f"    #{pupil['id']:<6} {pupil.get('fullName')!r}  {pupil.get('email')}")

    print(f"\n⚠ РОЛІ, ЯКІ БУЛИ В ЕКСПОРТІ Й ЗНИКЛИ З ПРІЗВИЩ: {len(dropped_roles)}")
    print("   (прізвища у ШС свіжіші на місяць, тож перемагають — але перевір)")
    for pupil, legacy, lost in dropped_roles:
        _, current = split_roles(pupil.get("lastName"))
        print(f"    #{pupil['id']:<6} {pupil.get('lastName')!r:<26} "
              f"було {legacy['Roles']!r} → лишається {['student'] + [r.lower() for r in current]}"
              f"   ВТРАЧЕНО: {lost}")

    print("\nПриклади документів:")
    for doc_id, doc in documents[:2]:
        preview = {k: v for k, v in doc.items() if k not in ("aiInfo", "possibleDuplicateId")}
        print(f"\n  {doc_id}")
        for key, value in preview.items():
            print(f"      {key:<20} {value!r}")

    roles_sample = [(d["lastName"], d["roles"]) for _, d in documents if len(d["roles"]) > 1]
    print(f"\nРолі понад student у {len(roles_sample)} учнів, приклади:")
    for last, roles in roles_sample[:8]:
        print(f"      {last!r:<28} {roles}")

    if not args.apply:
        print(f"\nПробний прогін. Щоб записати {len(documents)} документів — додай --apply")
        return

    print(f"\nЗаписую {len(documents)} документів…")
    written = 0
    for start in range(0, len(documents), BATCH_SIZE):
        batch = db.batch()
        for doc_id, doc in documents[start:start + BATCH_SIZE]:
            batch.create(db.collection(COLLECTION).document(doc_id), doc)
        await batch.commit()
        written += len(documents[start:start + BATCH_SIZE])
        print(f"  {written}/{len(documents)}")

    print(f"\nГотово. У колекції {COLLECTION}: {len(await existing_st_ids())} документів з ШС.")


if __name__ == "__main__":
    asyncio.run(main())
