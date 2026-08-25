"""Доповнення документів Firestore даними з бази лідів SchoolToday.

Ліди — це анкети, через які учні проходили до появи бота. Там лишились дані,
яких немає в картці учня: справжнє джерело ліда, нікнейм Telegram і медичні
деталі. Зіставлення йде по полю «Email студента» з leadCustomData — саме воно
відповідає пошті учня, тоді як `email` самого ліда належить батькові.

    python -m scripts.enrich_from_leads            # показати, що додасться
    python -m scripts.enrich_from_leads --apply

Потрібен ключ із функцією Leads:
    SCHOOL_TODAY_LEADS_KEY=...
"""
import argparse
import asyncio
import collections
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv()

from core.database import db  # noqa: E402
from core.schooltoday import normalize_nickname  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

BATCH_SIZE = 400
LEADS_KEY = os.getenv("SCHOOL_TODAY_LEADS_KEY") or os.getenv("SCHOOL_TODAY_API_KEY")

# Джерела зводимо до варіантів, які пропонує бот (bot/keyboards.py:get_lead_source_kb).
# Виняток — старе «з соц мереж»: воно не називає мережу, тож жодному з варіантів
# бота не відповідає. Помічаємо його як легасі, щоб воно не засмічувало канонічний
# список і водночас не злилося з рештою «Інше».
LEGACY_SOCIAL = "Інше: Соцмережі (старі)"

SOURCE_MAP = {
    "від друзів": "Від друзів",
    "від батьків": "Від батьків",
    "від вчителя": "Школа",
    "з соц мереж": LEGACY_SOCIAL,
    "інше": None,          # дивимось у «Інші джерела»
}

# Уточнення для тих, хто обрав «Інше» й дописав свій варіант
OTHER_PATTERNS = [
    (r"chat\s*gpt|чат\s*gpt|штучн|\bші\b", "ШІ"),
    (r"\bgoogle\b|гугл", "Google"),
    (r"телеграм|telegram|вайбер|viber", "Telegram-канал"),
    (r"вчител|школ|ліце|гімназ", "Школа"),
    (r"подруг|подружк|друз|сестр|брат", "Від друзів"),
    (r"інстаграм|instagram", "Instagram"),
    (r"tiktok|тікток", "TikTok"),
    (r"facebook|фейсбук", "Facebook"),
    (r"соц\s*мереж", LEGACY_SOCIAL),
    (r"організац|фестивал|ярмарок|виставц|вднг|форум|конференц|вебінар", "Організація"),
]

# Значення «Медичних даних», які нічого не повідомляють
MEDICAL_JUNK = {
    "-", ".", "/", "—", "ні", "немає", "не має", "нема", "не знаю", "так",
    "ні яких особливостей не має.", 'я відповів "ні"', "не потрібно", "0",
}


def fetch_leads() -> list[dict]:
    request = urllib.request.Request(
        "https://school-today.com/v1/Leads", headers={"X-API-Key": LEADS_KEY}
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        data = json.loads(response.read().decode("utf-8"))
    return data["leads"] if isinstance(data, dict) and "leads" in data else data


def custom(lead: dict, name: str) -> str:
    for entry in lead.get("leadCustomData") or []:
        if (entry.get("name") or "").strip() == name:
            return (entry.get("value") or "").strip()
    return ""


def map_source(lead: dict) -> str:
    """Джерело ліда у канонічному вигляді або порожній рядок."""
    raw = custom(lead, "Джерело ліда").strip().lower()
    mapped = SOURCE_MAP.get(raw, "")

    if mapped:
        return mapped
    if raw and raw not in SOURCE_MAP:
        return raw.capitalize()

    # «Інше» або порожньо — пробуємо витягти сенс із дописаного варіанта
    other = custom(lead, "Інші джерела").strip()
    if len(other) < 3:
        return "Інше" if raw == "інше" else ""
    for pattern, value in OTHER_PATTERNS:
        if re.search(pattern, other, re.I):
            return value
    return "Інше" if raw == "інше" else ""


def map_medical(lead: dict) -> str:
    value = custom(lead, "Медичні дані").strip()
    if not value or value.lower() in MEDICAL_JUNK or len(value) < 4:
        return ""
    return value


def pick_lead(candidates: list[dict]) -> dict:
    """Коли на одну пошту кілька лідів — беремо найзмістовніший, потім найновіший."""
    def score(lead):
        filled = sum(1 for c in (lead.get("leadCustomData") or [])
                     if (c.get("value") or "").strip() not in ("", "-", "."))
        return (filled, lead.get("createdDate") or "")
    return max(candidates, key=score)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--show", type=int, default=12)
    args = ap.parse_args()

    if not LEADS_KEY:
        sys.exit("Немає ключа: SCHOOL_TODAY_LEADS_KEY")

    leads = fetch_leads()
    by_email: dict[str, list[dict]] = {}
    for lead in leads:
        email = custom(lead, "Email студента").lower()
        if email:
            by_email.setdefault(email, []).append(lead)
    print(f"Лідів: {len(leads)}   унікальних пошт студента: {len(by_email)}")
    print(f"Пошт із кількома лідами: {sum(1 for v in by_email.values() if len(v) > 1)}\n")

    docs = []
    async for snap in db.collection("Svitlo").stream():
        docs.append((snap.id, snap.to_dict() or {}))
    print(f"Документів у Svitlo: {len(docs)}")

    changes, samples = [], collections.defaultdict(list)
    counts = collections.Counter()
    sources = collections.Counter()
    matched = 0

    for doc_id, doc in docs:
        email = (doc.get("email") or "").strip().lower()
        candidates = by_email.get(email)
        if not candidates:
            counts["без ліда"] += 1
            continue
        matched += 1
        lead = pick_lead(candidates)
        patch = {}

        # Нікнейм лишаємо наш — він свіжіший; беремо з ліда лише коли порожньо
        if not (doc.get("telegramUsername") or "").strip():
            nickname = normalize_nickname(custom(lead, "Телеграм Нікнейм студента"))
            if nickname and nickname not in ("@", "@-", "@."):
                patch["telegramUsername"] = nickname

        if not (doc.get("leadSource") or "").strip():
            source = map_source(lead)
            if source:
                patch["leadSource"] = source
                sources[source] += 1

        if not (doc.get("healthIssuesDetails") or "").strip():
            medical = map_medical(lead)
            if medical:
                patch["healthIssuesDetails"] = medical

        if not patch:
            counts["нічого додавати"] += 1
            continue
        for field, value in patch.items():
            counts[field] += 1
            if len(samples[field]) < args.show:
                samples[field].append((doc.get("firstName"), doc.get("lastName"), value))
        changes.append((doc_id, patch))

    print(f"Зіставлено з лідом: {matched}\n")
    print("=" * 74)
    print("ЩО ДОДАСТЬСЯ")
    print("=" * 74)
    for field in ("telegramUsername", "leadSource", "healthIssuesDetails"):
        print(f"\n{counts[field]:>5}  {field}")
        for first, last, value in samples[field]:
            print(f"        {first} {last}: {str(value)[:60]!r}")

    print("\n" + "=" * 74)
    print("РОЗПОДІЛ ДЖЕРЕЛ ПІСЛЯ ЗВЕДЕННЯ")
    print("=" * 74)
    for source, count in sources.most_common():
        print(f"  {count:>5}  {source}")

    print(f"\nБез ліда: {counts['без ліда']}   нічого додавати: {counts['нічого додавати']}")
    print(f"Документів до зміни: {len(changes)}")

    if not args.apply:
        print("\nПробний прогін. Щоб застосувати — додай --apply")
        return

    print("\nЗаписую…")
    written = 0
    for start in range(0, len(changes), BATCH_SIZE):
        batch = db.batch()
        for doc_id, patch in changes[start:start + BATCH_SIZE]:
            batch.update(db.collection("Svitlo").document(doc_id), patch)
        await batch.commit()
        written += len(changes[start:start + BATCH_SIZE])
        print(f"  {written}/{len(changes)}")
    print("Готово.")


if __name__ == "__main__":
    asyncio.run(main())
