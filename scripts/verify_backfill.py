"""Звірка документів Firestore проти обох джерел: ШС і старого експорту.

Проходить кожен документ із `createdVia == "import"`, знаходить картку в ШС за
`stPupilId` і рядок експорту за поштою, і порівнює поле за полем.

    python -m scripts.verify_backfill
    python -m scripts.verify_backfill --verbose   # показати й те, що збіглося
"""
import argparse
import asyncio
import collections
import csv
import glob
import json
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv()

from core import schooltoday as st  # noqa: E402
from core.database import db  # noqa: E402
from core.utils import normalize_phone  # noqa: E402
from scripts.backfill_firestore import (  # noqa: E402
    COLLECTION, LEGACY_CSV, SEMESTER_MAP, SEMESTER_LEGACY, SKIP_ST_IDS,
    custom, merge_roles, parse_birthday, split_roles,
)

sys.stdout.reconfigure(encoding="utf-8")

GENDER_FROM_ST = {0: "Male", 1: "Female"}
AGE_GROUP_FROM_ST = {"14-18 років": "older", "10-13 років": "younger"}


async def load_source():
    """Жива база ШС, зі знімком як запасним варіантом."""
    try:
        pupils = await st.list_pupils()
        parents = {p["id"]: p for p in await st.list_parents()}
        names = (await st.get_registry())["field_name"]
        return pupils, parents, names, "жива база ШС"
    except Exception as exc:  # мережа буває нестабільною
        snap = sorted(glob.glob(
            r"D:\Zabrik\SvitloSchool\work materials\st_backup\schooltoday_snapshot_*.json"))[-1]
        data = json.loads(Path(snap).read_text(encoding="utf-8"))
        names = data.get("_meta", {}).get("field_names")
        if not names:
            raise
        return (data["pupils"], {p["id"]: p for p in data["parents"]}, names,
                f"знімок {Path(snap).name} (жива база недоступна: {exc})")


def expected_document(pupil, parent, legacy, names) -> dict:
    """Що мало б лежати в документі, порахувавши з джерел наново."""
    last_name, _ = split_roles(pupil.get("lastName"))
    address = (pupil.get("address") or "").strip()
    city, _, country = (part.strip() for part in address.partition(","))
    roles, _ = merge_roles(pupil, legacy)
    nickname = custom(pupil, names["tg_nickname"]) or (legacy or {}).get("Telegram Nickname", "")
    tg_raw = (custom(pupil, names["tg_id"]) or (legacy or {}).get("Telegram ID", "")).strip()

    return {
        "firstName": (pupil.get("firstName") or "").strip(),
        "lastName": last_name,
        "email": (pupil.get("email") or "").strip().lower(),
        "gender": GENDER_FROM_ST.get(pupil.get("gender"), ""),
        "ageGroup": AGE_GROUP_FROM_ST.get(custom(pupil, names["age_group"]), None),
        "house": (pupil.get("pupilTypeName") or "").strip() or "Newbie",
        "semester": SEMESTER_MAP.get(custom(pupil, names["lead_source"]), SEMESTER_LEGACY),
        "roles": roles,
        "telegramId": int(tg_raw) if tg_raw.isdigit() else None,
        "telegramUsername": st.normalize_nickname(nickname),
        "hasGroupAccess": (legacy or {}).get("Group Access", "").strip().upper() == "YES",
        "hasHouseAccess": (legacy or {}).get("House Access", "").strip().upper() == "YES",
        "isDisplaced": custom(pupil, names["idp"]) == "Так",
        "displacedRegion": custom(pupil, names["idp_region"]),
        "hasHealthIssues": custom(pupil, names["health"]) == "Так",
        "healthIssuesDetails": custom(pupil, names["health_details"]),
        "city": city,
        "country": country,
        "stPupilId": pupil["id"],
        "stParentId": parent["id"] if parent else None,
        "parentFirstName": (parent.get("firstName") or "").strip() if parent else "",
        "parentLastName": (parent.get("lastName") or "").strip() if parent else "",
        "parentEmail": (parent.get("email") or "").strip().lower() if parent else "",
        "parentPhone": (normalize_phone(parent.get("phoneNumber")) or "") if parent else "",
        "stage": "student",
        "createdVia": "import",
        "phone": "",
        "leadSource": "",
        "followupStep": 0,
        "rulesMistakes": 0,
    }


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    pupils, parents, names, origin = await load_source()
    by_st_id = {p["id"]: p for p in pupils}
    legacy_by_email = {}
    for row in csv.DictReader(open(LEGACY_CSV, encoding="utf-8-sig")):
        email = (row["Email"] or "").strip().lower()
        if email:
            legacy_by_email[email] = row

    docs = []
    async for snap in db.collection(COLLECTION).stream():
        data = snap.to_dict() or {}
        if data.get("createdVia") == "import":
            docs.append((snap.id, data))

    print(f"Джерело звірки: {origin}")
    print(f"Документів з createdVia=import у Firestore: {len(docs)}\n")
    if not docs:
        print("Нема чого звіряти.")
        return

    problems = collections.Counter()
    checked = 0
    for doc_id, data in sorted(docs, key=lambda d: d[1].get("stPupilId") or 0):
        st_id = data.get("stPupilId")
        pupil = by_st_id.get(st_id)
        print("=" * 70)
        print(f"{doc_id}   stPupilId={st_id}   {data.get('firstName')} {data.get('lastName')}")

        if not pupil:
            print("  ✗ КАРТКИ У ШС НЕМАЄ")
            problems["немає у ШС"] += 1
            continue
        if st_id in SKIP_ST_IDS:
            print("  ✗ ЦЕ СЛУЖБОВА/ТЕСТОВА КАРТКА — не мала потрапити")
            problems["службова картка"] += 1

        parent_ids = pupil.get("parentIDs") or []
        parent = parents.get(parent_ids[0]) if parent_ids else None
        legacy = legacy_by_email.get((pupil.get("email") or "").strip().lower())
        if legacy is None:
            print("  ! пари в старому експорті немає (доступи й Telegram ID будуть порожні)")

        expected = expected_document(pupil, parent, legacy, names)
        bad = []
        for key, want in expected.items():
            got = data.get(key)
            if key == "ageGroup" and want is None:
                continue
            if got != want:
                bad.append((key, got, want))

        birth_want = parse_birthday(pupil.get("birthday"))
        birth_got = data.get("birthDate")
        if birth_want and birth_got:
            if birth_want.date() != birth_got.date():
                bad.append(("birthDate", birth_got, birth_want))
        elif birth_want or birth_got:
            bad.append(("birthDate", birth_got, birth_want))

        if not doc_id.startswith("SV-") or not re.match(r"^SV-\d{6}-[0-9a-f]{8}$", doc_id):
            bad.append(("_docId", doc_id, "SV-YYMMDD-XXXXXXXX"))

        for field in ("createdAt", "stageUpdatedAt"):
            if not data.get(field):
                bad.append((field, None, "має бути час імпорту"))

        if bad:
            for key, got, want in bad:
                print(f"  ✗ {key:<20} у Firestore {got!r}")
                print(f"    {'':<20} очікували  {want!r}")
                problems[key] += 1
        else:
            print("  ✓ усі поля збігаються")
        checked += 1

        if args.verbose:
            print(f"    roles={data.get('roles')}  semester={data.get('semester')!r}  "
                  f"tgId={data.get('telegramId')}  групa={data.get('hasGroupAccess')}")

    print("\n" + "=" * 70)
    print(f"Звірено {checked} документів")
    if problems:
        print("Розбіжності:")
        for key, count in problems.most_common():
            print(f"  {count:>4}  {key}")
    else:
        print("Розбіжностей немає.")


if __name__ == "__main__":
    asyncio.run(main())
