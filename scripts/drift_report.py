"""Пошук ручних правок у SchoolToday — до того, як синк їх затре.

Синхронізація однобічна: Firestore пише в ШС. Але інтерфейс ШС нікуди не
подівся, і будь-хто може поправити картку там. Наступний синк це мовчки
відкотить, а людині, чия правка зникла, це виглядатиме як баг.

Скрипт нічого не змінює. Він порівнює три стани:

    ШС зараз  ←── що ми запушили минулого разу ──→  Firestore зараз

і розкладає відмінності на три купи:

  * ШС змінили руками   — хтось поправив картку в інтерфейсі школи
  * ми змінили          — правка у Firestore, ще не запушена
  * розійшлись обидва   — конфлікт, потрібне рішення людини

    python -m scripts.drift_report
    python -m scripts.drift_report --show 40
"""
import argparse
import asyncio
import collections
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv()

from core import schooltoday as st  # noqa: E402
from core.database import db  # noqa: E402
from core.utils import normalize_phone  # noqa: E402
from scripts.sync_to_schooltoday import (  # noqa: E402
    SYNC_STATE, actual_from_st, owned_values,
)

sys.stdout.reconfigure(encoding="utf-8")


def flatten(values: dict) -> dict:
    flat = {k: v for k, v in values.items() if k != "_parent"}
    for key, value in (values.get("_parent") or {}).items():
        flat[f"батько.{key}"] = value
    return flat


def differs(a, b) -> bool:
    """Порожні значення вважаємо однаковими: None, '' і відсутність — це те саме."""
    if a in (None, "") and b in (None, ""):
        return False
    return a != b


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", type=int, default=20)
    args = ap.parse_args()

    registry = await st.get_registry()
    names = registry["field_name"]
    pupils = {p["id"]: p for p in await st.list_pupils()}
    parents = {p["id"]: p for p in await st.list_parents()}

    docs = {}
    async for snap in db.collection("Svitlo").stream():
        data = snap.to_dict() or {}
        data["_id"] = snap.id
        docs[snap.id] = data

    baselines = {}
    async for snap in db.collection(SYNC_STATE).stream():
        baselines[snap.id] = (snap.to_dict() or {}).get("values") or {}

    print(f"Firestore {len(docs)} · ШС {len(pupils)} учнів, {len(parents)} батьків")
    print(f"Зафіксованих станів синхронізації: {len(baselines)}\n")

    if not baselines:
        print("Базових станів немає — спершу прожени `sync_to_schooltoday --apply`,")
        print("він запише, що саме було відправлено. Без цього напрямок правки")
        print("обчислити неможливо: у ШС немає позначки часу оновлення.")
        return

    st_edited = collections.defaultdict(list)
    ours_pending = collections.defaultdict(list)
    not_pushed = collections.defaultdict(list)
    conflicts = collections.defaultdict(list)
    no_baseline = []
    duplicates = collections.Counter()
    dup_conflicting = []

    for doc_id, doc in docs.items():
        pupil = pupils.get(doc.get("stPupilId"))
        if not pupil:
            continue
        baseline = baselines.get(doc_id)
        if baseline is None:
            no_baseline.append(doc_id)
            continue

        parent = parents.get(doc.get("stParentId"))
        actual = flatten(actual_from_st(pupil, parent, names))
        desired = flatten(owned_values(doc, names, registry))
        base = flatten(baseline)

        who = f"{doc.get('firstName')} {doc.get('lastName')}".strip()

        per_name = collections.Counter((c.get("name") or "").strip()
                                       for c in (pupil.get("customData") or []))
        for name, count in per_name.items():
            if count > 1:
                duplicates[name] += 1
                values = {(c.get("value") or "").strip()
                          for c in pupil["customData"]
                          if (c.get("name") or "").strip() == name}
                if len(values) > 1:
                    dup_conflicting.append((doc_id, who, name, sorted(values)))

        for field in desired:
            b, a, d = base.get(field), actual.get(field), desired.get(field)
            st_changed = differs(a, b)
            we_changed = differs(d, b)
            if st_changed and we_changed:
                conflicts[field].append((doc_id, who, b, a, d))
            elif st_changed:
                st_edited[field].append((doc_id, who, b, a))
            elif we_changed:
                # Порожнє значення з нашого боку ми свідомо не пушимо, щоб не
                # затирати дані школи — така різниця не «чекає на синк», вона
                # постійна за побудовою. Те саме з ПІБ батька: коли ім'я
                # порожнє, синк пропускає обидва поля разом, бо ШС не приймає
                # порожнє firstName.
                parent_name_skipped = (
                    field.startswith("батько.")
                    and not (doc.get("parentFirstName") or "").strip()
                )
                if d in (None, "") or parent_name_skipped:
                    not_pushed[field].append((doc_id, who, b))
                else:
                    ours_pending[field].append((doc_id, who, b, d))

    print("=" * 76)
    print("ПОПРАВИЛИ РУКАМИ В ШС — наступний синк це відкотить")
    print("=" * 76)
    if not st_edited:
        print("\n  Немає.")
    for field, items in sorted(st_edited.items(), key=lambda kv: -len(kv[1])):
        print(f"\n{len(items):>5}  {field}")
        for doc_id, who, was, now in items[:args.show]:
            print(f"        {who}: було {was!r} → у ШС зараз {now!r}   [{doc_id}]")
        if len(items) > args.show:
            print(f"        … ще {len(items) - args.show}")

    print("\n" + "=" * 76)
    print("КОНФЛІКТИ — змінили з обох боків, потрібне рішення")
    print("=" * 76)
    if not conflicts:
        print("\n  Немає.")
    for field, items in conflicts.items():
        print(f"\n{len(items):>5}  {field}")
        for doc_id, who, was, in_st, ours in items[:args.show]:
            print(f"        {who}: було {was!r}")
            print(f"              ШС {in_st!r}   ми {ours!r}   [{doc_id}]")

    print("\n" + "=" * 76)
    print("НАШІ ЗМІНИ, ЩЕ НЕ ЗАПУШЕНІ — поїдуть наступним синком")
    print("=" * 76)
    if not ours_pending:
        print("\n  Немає.")
    for field, items in sorted(ours_pending.items(), key=lambda kv: -len(kv[1])):
        print(f"  {len(items):>5}  {field}")
        for doc_id, who, was, now in items[:3]:
            print(f"            {who}: {was!r} → {now!r}")

    print("\n" + "=" * 76)
    print("РІЗНИЦЯ, ЯКУ МИ СВІДОМО НЕ ПЕРЕНОСИМО")
    print("=" * 76)
    print("У Firestore порожньо, у ШС є значення. Порожні значення не пушимо,")
    print("щоб не затирати дані школи — тож ця різниця постійна, не помилка.\n")
    if not not_pushed:
        print("  Немає.")
    for field, items in sorted(not_pushed.items(), key=lambda kv: -len(kv[1])):
        print(f"  {len(items):>5}  {field}")

    print("\n" + "=" * 76)
    print("ДУБЛІКАТИ В customData НА БОЦІ ШС")
    print("=" * 76)
    if not duplicates:
        print("\n  Немає.")
    else:
        print("`PATCH` не прибирає повторні записи з тим самим іменем, хоча")
        print("документація обіцяє повну заміну масиву. Читаємо перший запис.\n")
        for name, count in duplicates.most_common():
            print(f"  {count:>5}  {name!r}")
        if dup_conflicting:
            print(f"\n  ⚠ де значення в дублях РІЗНІ — {len(dup_conflicting)}:")
            for doc_id, who, name, values in dup_conflicting[:args.show]:
                print(f"      {who}: {name!r} = {values}   [{doc_id}]")

    if no_baseline:
        print(f"\n{len(no_baseline)} документів без зафіксованого стану — "
              f"їх ще жодного разу не синхронізували")

    total_st = sum(len(v) for v in st_edited.values())
    total_conf = sum(len(v) for v in conflicts.values())
    total_ours = sum(len(v) for v in ours_pending.values())
    print("\n" + "=" * 76)
    print(f"Правок у ШС: {total_st}   конфліктів: {total_conf}   наших до пушу: {total_ours}")
    if total_st or total_conf:
        print("\nПерш ніж запускати синк — розберись із цим списком: те, що поправили")
        print("в ШС, буде замінено значеннями з Firestore.")
    else:
        print("Розходжень, що потребують дії, немає.")


if __name__ == "__main__":
    asyncio.run(main())
