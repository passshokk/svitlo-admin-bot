"""Одноразове зарахування у SchoolToday документа, заведеного у Firestore вручну.

`scripts.sync_to_schooltoday` картку в ШС НЕ створює: він шукає її за `stPupilId`
і лише оновлює наявні. Документ без `stPupilId` синк просто пропускає. Створює
картку `core.schooltoday.enroll` — картка батька, картка учня, зв'язок і
`grantAccess` + лист-запрошення учневі (те саме, що робить approve у Solar
Panel). Ідемпотентно за `externalID` (= doc_id), тож повторний запуск дубля не
створить. Після успіху `stPupilId`/`stParentId` пишуться назад у документ.

    python -m scripts.enroll_one SV-260903-abcdef01          # прев'ю
    python -m scripts.enroll_one SV-260903-abcdef01 --apply  # зарахувати
    python -m scripts.enroll_one "Babka Oleksandr"           # знайти doc_id за іменем
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
from core.database import db  # noqa: E402

SHOWN_FIELDS = ("firstName", "lastName", "birthDate", "gender", "email",
                "ageGroup", "house", "parentFirstName", "parentLastName", "parentPhone")


async def resolve_doc_id(who: str) -> str:
    """Приймає або готовий doc_id (SV-…), або підрядок ПІБ — тоді шукає по колекції."""
    if who.upper().startswith("SV-"):
        return who

    needle = who.lower().strip()
    matches = []
    async for snap in db.collection("Svitlo").stream():
        d = snap.to_dict() or {}
        full = f"{d.get('firstName', '')} {d.get('lastName', '')}".strip().lower()
        if needle in full:
            matches.append((snap.id, full, d.get("stage")))

    if not matches:
        sys.exit(f"За запитом {who!r} нікого не знайдено у Svitlo")
    if len(matches) > 1:
        print(f"Знайдено {len(matches)} — уточни doc_id:")
        for doc_id, full, stage in matches:
            print(f"  {doc_id}  {full}  (stage={stage})")
        sys.exit(1)
    return matches[0][0]


async def main(argv: list[str] | None = None):
    ap = argparse.ArgumentParser()
    ap.add_argument("who", help="doc_id (SV-…) або підрядок ПІБ")
    ap.add_argument("--apply", action="store_true", help="без нього — лише показати, що буде")
    args = ap.parse_args(argv)

    doc_id = await resolve_doc_id(args.who)
    snap = await db.collection("Svitlo").document(doc_id).get()
    if not snap.exists:
        sys.exit(f"Документ {doc_id} у Svitlo не знайдено")
    doc = snap.to_dict() or {}

    print(f"{doc_id}   stage={doc.get('stage')!r}")
    for field in SHOWN_FIELDS:
        print(f"    {field}: {doc.get(field)!r}")
    if doc.get("stPupilId"):
        print(f"\n⚠ stPupilId={doc['stPupilId']} уже стоїть — картка в ШС, схоже, вже є. "
              "enroll ідемпотентний, але звір, чи це не помилка.")

    if not args.apply:
        print("\nПробний прогін. Щоб зарахувати в ШС — додай --apply")
        return

    print("\nЗараховую…")
    result = await st.enroll(doc_id, doc)
    await db.collection("Svitlo").document(doc_id).update({
        "stPupilId": result["pupilId"],
        "stParentId": result["parentId"],
    })
    print(f"Готово: stPupilId={result['pupilId']}  stParentId={result['parentId']}")


if __name__ == "__main__":
    asyncio.run(main())
