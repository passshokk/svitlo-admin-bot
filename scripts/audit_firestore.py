"""Стан колекції Svitlo перед міграцією. Лише читання.

Показує, скільки документів уже є, які в них поля і чи перетинаються вони з
базою SchoolToday по пошті — щоб бекфіл не наплодив дублікатів.

    python -m scripts.audit_firestore
"""
import asyncio
import collections
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

# Щоб працювало і як `python -m scripts.audit_firestore`, і як прямий запуск файлу
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

load_dotenv()

from core.database import db  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

SNAPSHOT_DIR = Path(r"D:\Zabrik\SvitloSchool\work materials\st_backup")


async def main():
    docs = [d async for d in db.collection("Svitlo").stream()]
    print(f"КОЛЕКЦІЯ Svitlo: {len(docs)} документів\n")

    if not docs:
        print("  Колекція порожня — бекфіл піде на чисте поле.")
        return

    stages = collections.Counter()
    fields = collections.Counter()
    emails = {}
    id_shapes = collections.Counter()

    for d in docs:
        data = d.to_dict() or {}
        stages[data.get("stage") or data.get("crm_stage") or "—"] += 1
        fields.update(data.keys())
        email = (data.get("email") or "").strip().lower()
        if email:
            emails.setdefault(email, []).append(d.id)
        prefix = d.id[:3] if len(d.id) > 3 else "?"
        id_shapes[prefix if prefix == "SV-" else "інший формат"] += 1

    print("Етапи:")
    for k, v in stages.most_common():
        print(f"  {v:>5}  {k}")

    print(f"\nФормат ID: {dict(id_shapes)}")

    print(f"\nПоля (у скількох документів зустрічається):")
    for k, v in fields.most_common():
        print(f"  {v:>5}  {k}")

    dup = {k: v for k, v in emails.items() if len(v) > 1}
    print(f"\nДокументів з поштою: {len(emails)}   пошт-дублікатів: {len(dup)}")

    snapshots = sorted(SNAPSHOT_DIR.glob("*.json"))
    if not snapshots:
        print("\n⚠ Знімка ШС не знайдено — перетин не перевірено.")
        return

    snap = json.loads(snapshots[-1].read_text(encoding="utf-8"))
    st_active = [p for p in snap["pupils"] if not p.get("isHidden")]
    st_emails = {}
    for p in st_active:
        e = (p.get("email") or "").strip().lower()
        if e:
            st_emails.setdefault(e, []).append(p["id"])

    overlap = set(emails) & set(st_emails)
    print(f"\n{'=' * 62}")
    print(f"ПЕРЕТИН ІЗ ШС (знімок {snapshots[-1].name})")
    print(f"{'=' * 62}")
    print(f"  активних учнів у ШС:        {len(st_active)}")
    print(f"  з них уже є у Firestore:    {len(overlap)}")
    print(f"  потребують створення:       {len(st_emails) - len(overlap)}")
    print(f"  у Firestore без пари в ШС:  {len(set(emails) - set(st_emails))}")

    if overlap:
        print("\n  Приклади збігів (їх треба оновити, а не створювати):")
        for e in list(overlap)[:5]:
            print(f"    {e[:3]}…@… → Firestore {emails[e]}  ШС {st_emails[e]}")


if __name__ == "__main__":
    asyncio.run(main())
