"""Пошук дублікатів у Firestore (Svitlo), серед яких хоча б одна картка
неактивна або неактуальна. Нічого не змінює — лише показує кластери.

Дублем вважаємо документи, що збігаються хоч за одним ідентифікатором САМОЇ
дитини: email, телефон, Telegram ID або ПІБ+дата народження. Пошта й
телефон БАТЬКІВ навмисно не є ключами дублікації — на відміну від решти
полів, вони очікувано повторюються в рідних братів/сестер, і без цього
винятку звіт тонув у сотнях "дублів", які насправді просто сіблінги
(перевірено вручну на живих даних: прибирання батьківських полів із ключів
не загубило жодного справжнього дубля — той самий кластер завжди ловився
ще й за email/ПІБ+ДН дитини). Ключі об'єднуються (union-find), тож ланцюжок
A=B за поштою, B=C за Telegram ID потрапляє в один кластер.

Для кожної картки в кластері визначається вердикт:
  student/alumni       -> АКТИВНА (зарахований/випускник)
  blocked              -> НЕАКТИВНА (заблокована)
  застрягла в воронці   -> ЗАСТАРІЛА (давно без руху; пороги ті самі,
                           що в панелі — core/pipeline.py STALLED_HOURS_BY_STAGE)
  минулий семестр, лід   -> НЕАКТУАЛЬНА (семестр змінився, а заявка так і не
                           дійшла до student/blocked)
  інше                 -> У ПРОЦЕСІ (свіжа, ще рухається воронкою)

Кластер, де є хоча б одна АКТИВНА і хоча б одна НЕАКТИВНА/ЗАСТАРІЛА/
НЕАКТУАЛЬНА картка — головний кандидат на чистку: стара картка дублює
живу. Кластери без жодної активної картки виводяться окремо — там нема з
чим звіряти, рішення потребує людини.

    python -m scripts.find_inactive_duplicates
    python -m scripts.find_inactive_duplicates --show 50
"""
import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv()

from core.database import db, get_current_semester  # noqa: E402
from core.utils import normalize_phone  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

# Дзеркало core/pipeline.py (svitlo_admin_panel) — тримаємо синхронізованим
# вручну, бо бот і панель живуть у різних репозиторіях/venv і не імпортують
# одне одного. Стадія, якої тут немає, дістає STALLED_AFTER_DAYS.
STALLED_AFTER_DAYS = 3
STALLED_HOURS_BY_STAGE = {
    "admin_review": 24,
    "uploading_docs": 3 * 24,
    "rules_matching": 3 * 24,
    "personal_data": 3 * 24,
}
TERMINAL_STAGES = ("student", "alumni", "blocked")


def stalled_after_hours(stage: str) -> int:
    return STALLED_HOURS_BY_STAGE.get(stage, STALLED_AFTER_DAYS * 24)


def as_utc(value) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def days_ago(value) -> str:
    dt = as_utc(value)
    if not dt:
        return "?"
    n = (datetime.now(timezone.utc) - dt).days
    return f"{n} дн. тому" if n >= 0 else "?"


def classify(d: dict, current_semester: str) -> str:
    stage = d.get("stage") or ""
    if stage == "student":
        return "АКТИВНА"
    if stage == "alumni":
        return "АКТИВНА (випускник)"
    if stage == "blocked":
        return "НЕАКТИВНА (заблокована)"

    updated = as_utc(d.get("stageUpdatedAt")) or as_utc(d.get("createdAt"))
    if updated:
        idle_hours = (datetime.now(timezone.utc) - updated).total_seconds() / 3600
        if idle_hours >= stalled_after_hours(stage):
            semester = (d.get("semester") or "").strip()
            if semester and semester != current_semester:
                return "НЕАКТУАЛЬНА (минулий семестр, лід не дійшов до кінця)"
            return "ЗАСТАРІЛА (застряг у воронці)"

    return "У ПРОЦЕСІ"


class UnionFind:
    def __init__(self):
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def dup_keys(doc_id: str, d: dict) -> list[tuple[str, str]]:
    """Ключі дублікації для одного документа: (тип, нормалізоване значення)."""
    keys = []

    email = (d.get("email") or "").strip().lower()
    if email:
        keys.append(("email", email))

    phone = normalize_phone(d.get("phone") or "")
    if phone:
        keys.append(("phone", phone))

    tg_id = d.get("telegramId")
    if tg_id:
        keys.append(("telegramId", str(tg_id)))

    first, last = (d.get("firstName") or "").strip().lower(), (d.get("lastName") or "").strip().lower()
    birth = d.get("birthDate")
    birth_key = birth.date().isoformat() if isinstance(birth, datetime) else (str(birth).strip() if birth else "")
    if first and last and birth_key:
        keys.append(("ПІБ+ДН", f"{first} {last} {birth_key}"))

    return keys


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", type=int, default=20, help="скільки кластерів деталізувати на розділ")
    ap.add_argument("--detail", action="store_true",
                     help="показати email/телефон/tgId/stPupilId/доступи й для інших розділів "
                          "(розділ «Дублі серед студентів» деталізується завжди)")
    args = ap.parse_args()

    docs = []
    async for snap in db.collection("Svitlo").stream():
        docs.append((snap.id, snap.to_dict() or {}))
    print(f"Документів у Svitlo: {len(docs)}")

    current_semester = await get_current_semester()
    print(f"Поточний семестр: {current_semester}\n")

    uf = UnionFind()
    key_owner: dict[tuple[str, str], list[str]] = {}
    for doc_id, d in docs:
        uf.find(doc_id)
        for key in dup_keys(doc_id, d):
            key_owner.setdefault(key, []).append(doc_id)

    for owners in key_owner.values():
        for other in owners[1:]:
            uf.union(owners[0], other)

    by_data = dict(docs)
    clusters: dict[str, list[str]] = {}
    for doc_id, _ in docs:
        clusters.setdefault(uf.find(doc_id), []).append(doc_id)
    clusters = {root: ids for root, ids in clusters.items() if len(ids) > 1}

    # Для кожного кластера — за якими ключами саме він зійшовся (для заголовка).
    cluster_match_types: dict[str, set[str]] = {}
    for (ktype, _), owners in key_owner.items():
        if len(owners) < 2:
            continue
        root = uf.find(owners[0])
        cluster_match_types.setdefault(root, set()).add(ktype)

    actionable = []  # є і активна, і неактивна/застаріла/неактуальна картка
    ambiguous = []    # немає жодної активної — рішення за людиною
    all_active = []   # кілька активних карток одночасно (конфлікт, не сміття)

    for root, ids in clusters.items():
        verdicts = {doc_id: classify(by_data[doc_id], current_semester) for doc_id in ids}
        actives = [i for i, v in verdicts.items() if v.startswith("АКТИВНА")]
        stale = [i for i, v in verdicts.items() if not v.startswith("АКТИВНА")]
        if actives and stale:
            actionable.append((root, ids, verdicts))
        elif not actives:
            ambiguous.append((root, ids, verdicts))
        else:
            all_active.append((root, ids, verdicts))

    def print_cluster(root, ids, verdicts, limit, detail=False):
        keys = ", ".join(sorted(cluster_match_types.get(root, set()))) or "?"
        print(f"\n  Кластер за [{keys}] — {len(ids)} карток")
        for doc_id in ids[:limit]:
            d = by_data[doc_id]
            name = f"{d.get('firstName', '')} {d.get('lastName', '')}".strip() or "(без імені)"
            print(f"      {doc_id}  {name!r:35}  stage={d.get('stage') or '—':16}"
                  f" sem={d.get('semester') or '—':10} {days_ago(d.get('stageUpdatedAt') or d.get('createdAt')):15}"
                  f" -> {verdicts[doc_id]}")
            if detail:
                created = as_utc(d.get("createdAt"))
                print(f"          email={d.get('email') or '—':30} phone={d.get('phone') or '—':16}"
                      f" tgId={d.get('telegramId') or '—':12} tgUser=@{d.get('telegramUsername') or '—'}")
                print(f"          stPupilId={d.get('stPupilId') or '—':10} hasGroupAccess={d.get('hasGroupAccess')!s:6}"
                      f" hasHouseAccess={d.get('hasHouseAccess')!s:6} house={d.get('house') or '—':10}"
                      f" roles={d.get('roles') or []}")
                print(f"          createdAt={created.strftime('%Y-%m-%d %H:%M') if created else '—'}")
        if len(ids) > limit:
            print(f"      … ще {len(ids) - limit}")

    print("=" * 88)
    print("КАНДИДАТИ НА ЧИСТКУ — у кластері є і активна, і неактивна/застаріла картка")
    print("=" * 88)
    if not actionable:
        print("\n  Немає.")
    for root, ids, verdicts in sorted(actionable, key=lambda c: -len(c[1])):
        print_cluster(root, ids, verdicts, args.show, detail=args.detail)

    print("\n" + "=" * 88)
    print("НЕЯСНО — усі картки в кластері неактивні/застарілі, немає з чим звірити")
    print("=" * 88)
    if not ambiguous:
        print("\n  Немає.")
    for root, ids, verdicts in sorted(ambiguous, key=lambda c: -len(c[1])):
        print_cluster(root, ids, verdicts, args.show, detail=args.detail)

    if all_active:
        print("\n" + "=" * 88)
        print("ДУБЛІ СЕРЕД СТУДЕНТІВ — обидві картки вже student/alumni (не сміття, "
              "рішення за людиною: яку картку лишити)")
        print("=" * 88)
        for root, ids, verdicts in sorted(all_active, key=lambda c: -len(c[1])):
            print_cluster(root, ids, verdicts, args.show, detail=True)

    print("\n" + "=" * 88)
    print(f"Кластерів дублів: {len(clusters)}  "
          f"(кандидатів на чистку: {len(actionable)}, неясних: {len(ambiguous)}, конфліктів: {len(all_active)})")
    print("\nЦе лише звіт: жоден документ не змінено й не видалено.")
    print("Видаляти вручну через панель або core.database.delete_student — після перевірки очима.")


if __name__ == "__main__":
    asyncio.run(main())
