# core/sync_ops.py
"""Перенесення даних із Firestore у SchoolToday.

Firestore — джерело істини. Синхронізація однобічна: те, що змінили у нас,
їде в ШС. Зворотного напрямку немає свідомо — без нього не буває конфліктів,
а отже й тихих затирань.

Живе в `core/`, а не в `scripts/`, бо цю логіку викликає не лише
`python -m scripts.sync_to_schooltoday` з консолі, а й
`api/admin_routes.py` (owner-панель, кнопка «Синк»). `scripts/` навмисно
не їде в прод-контейнер (.gcloudignore) — тож усе, що там імпортується
самим ботом, мусить лежати тут.

Чого НЕ чіпаємо взагалі:
  * personalFileNumber, contractNumber, discount, oneTimeMealPayment, isPayer,
    hideInDiary — бізнес-поля школи, у нашій схемі їх немає;
  * isHidden — деактивація лишається ручною дією в інтерфейсі ШС;
  * email — ШС застосовує його лише поки немає доступу, а 164 картки батьків
    ділять пошту з дитиною і можуть впертись у валідацію;
  * grantAccess батькам — за рішенням команди поки не вмикаємо;
  * кастомне поле «Ролі» — його веде школа, ми лише читаємо й переносимо.

Прапорець `--strict` вмикає повну заміну `customData`: у ШС лишається рівно те,
що є у Firestore, плюс «Ролі». Усе інше зникає — так чистяться і застарілі
значення, і дублікати. «House» та «Вікова група» при цьому очищаються навмисно:
це копії нативних `pupilTypeID` і `classID`, які підлягають видаленню в
налаштуваннях школи.
"""
import argparse
import collections
from datetime import datetime, timezone

from core import schooltoday as st
from core.database import db
from core.utils import normalize_phone

GENDER_TO_ST = {"Male": 0, "Female": 1}
AGE_GROUP_TO_ST = {"older": "14-18 років", "younger": "10-13 років"}
CLASS_BY_AGE_GROUP = {"older": "Older Student", "younger": "Younger Student"}


SYNC_STATE = "SyncState"
BATCH_SIZE = 400  # ліміт Firestore — 500 операцій на батч


def actual_from_st(pupil: dict, parent: dict | None, names: dict) -> dict:
    """Поточний стан наших полів у ШС — у тому ж вигляді, що й owned_values.

    213 карток мають по кілька записів з одним іменем: `PATCH` не прибирає
    дублікати, хоча документація обіцяє повну заміну масиву. Читаємо ПЕРШИЙ
    запис — так само, як `merge_custom_data` обирає значення при записі, тож
    прочитане збігається із записаним.
    """
    custom = {}
    for entry in pupil.get("customData") or []:
        name = (entry.get("name") or "").strip()
        if name and name not in custom:
            custom[name] = (entry.get("value") or "").strip()
    values = {
        "firstName": (pupil.get("firstName") or "").strip(),
        "lastName": (pupil.get("lastName") or "").strip(),
        "gender": pupil.get("gender"),
        "classID": pupil.get("classID"),
        "pupilTypeID": pupil.get("pupilTypeID"),
        "phoneNumber": normalize_phone(pupil.get("phoneNumber")) or "",
    }
    for alias in ("health", "health_details", "lead_source",
                  "tg_nickname", "tg_id", "semester", "idp", "idp_region"):
        values[names[alias]] = custom.get(names[alias], "")
    values["_parent"] = {
        "firstName": (parent.get("firstName") or "").strip() if parent else "",
        "lastName": (parent.get("lastName") or "").strip() if parent else "",
        "phoneNumber": (normalize_phone(parent.get("phoneNumber")) or "") if parent else "",
    }
    return values


def synced_state(pupil: dict, parent: dict | None, names: dict,
                 patch: dict, custom_updates: dict, p_patch: dict) -> dict:
    """Що опиниться в ШС після застосування наших правок.

    Саме це, а не «бажаний» стан, є коректним baseline. Ми свідомо не пушимо
    порожні значення, щоб не затирати дані школи, тож у частині полів ШС
    лишається зі своїм вмістом — і записувати туди наш порожній рядок означало б
    потім щоразу бачити хибне «поправили руками».
    """
    state = actual_from_st(pupil, parent, names)
    for field in ("firstName", "lastName", "gender", "classID", "pupilTypeID", "phoneNumber"):
        if field in patch:
            state[field] = patch[field]
    state.update(custom_updates)
    for field in ("firstName", "lastName", "phoneNumber"):
        if field in p_patch:
            state["_parent"][field] = p_patch[field]
    return state


def owned_values(doc: dict, names: dict, registry: dict) -> dict:
    """Канонічний стан полів, які веде Firestore — «бажане» для порівняння."""
    class_name = CLASS_BY_AGE_GROUP.get(doc.get("ageGroup"))
    return {
        "firstName": (doc.get("firstName") or "").strip(),
        "lastName": (doc.get("lastName") or "").strip(),
        "gender": GENDER_TO_ST.get(doc.get("gender")),
        "classID": registry["class_id"].get(class_name) if class_name else None,
        "pupilTypeID": registry["pupil_type_id"].get((doc.get("house") or "").strip()),
        "phoneNumber": normalize_phone(doc.get("phone")) or "",
        names["health"]: "Так" if doc.get("hasHealthIssues") else "Ні",
        names["health_details"]: (doc.get("healthIssuesDetails") or "").strip(),
        names["lead_source"]: (doc.get("leadSource") or "").strip(),
        names["tg_nickname"]: (doc.get("telegramUsername") or "").strip(),
        names["tg_id"]: str(doc.get("telegramId") or ""),
        names["semester"]: (doc.get("semester") or "").strip(),
        names["idp"]: "Так" if doc.get("isDisplaced") else "Ні",
        names["idp_region"]: (doc.get("displacedRegion") or "").strip(),
        "_parent": {
            "firstName": (doc.get("parentFirstName") or "").strip(),
            "lastName": (doc.get("parentLastName") or "").strip(),
            "phoneNumber": normalize_phone(doc.get("parentPhone")) or "",
        },
    }


def parent_key(parent_id: int, phone: str) -> str:
    """Ключ батька: з телефону, а без нього — детерміновано з ID картки.

    Провідні нулі в E.164 неможливі, тож синтетичний ключ ніколи не зіткнеться
    зі справжнім. Виводиться з ID, тому не потребує збереженого мапінгу і
    однаковий при кожному прогоні.
    """
    normalized = normalize_phone(phone)
    if normalized:
        return "P-" + normalized.lstrip("+")
    return f"P-{parent_id:012d}"


# Кастомні поля, яких у Firestore немає і які веде школа. При повній заміні
# масиву їх треба явно переносити зі старої картки — інакше вони зітруться.
# «House» і «Вікова група» сюди НЕ входять: це застарілі копії нативних полів
# (pupilTypeID та classID), які підлягають видаленню в налаштуваннях школи.
SCHOOL_OWNED = ("roles",)


async def pupil_patch(doc: dict, pupil: dict, names: dict, registry: dict,
                      strict: bool = False) -> dict:
    patch: dict = {}

    if not (pupil.get("externalID") or "").strip():
        patch["externalID"] = doc["_id"]

    for ours, theirs in (("firstName", "firstName"), ("lastName", "lastName")):
        value = (doc.get(ours) or "").strip()
        if value and value != (pupil.get(theirs) or "").strip():
            patch[theirs] = value

    gender = GENDER_TO_ST.get(doc.get("gender"))
    if gender is not None and gender != pupil.get("gender"):
        patch["gender"] = gender

    class_name = CLASS_BY_AGE_GROUP.get(doc.get("ageGroup"))
    class_id = registry["class_id"].get(class_name) if class_name else None
    if class_id and class_id != pupil.get("classID"):
        patch["classID"] = class_id

    house = (doc.get("house") or "").strip()
    type_id = registry["pupil_type_id"].get(house)
    if type_id and type_id != pupil.get("pupilTypeID"):
        patch["pupilTypeID"] = type_id

    current_phone = (pupil.get("phoneNumber") or "").strip()
    phone = normalize_phone(doc.get("phone"))
    # Як і з телефоном батька: якщо в ШС уже кілька номерів через кому,
    # normalize_phone розпізнає лише перший — не чіпаємо, щоб не стерти
    # запасні контакти, введені вручну.
    if phone and phone != current_phone and "," not in current_phone:
        patch["phoneNumber"] = phone

    updates = {}
    values = {
        names["health"]: "Так" if doc.get("hasHealthIssues") else "Ні",
        names["health_details"]: (doc.get("healthIssuesDetails") or "").strip(),
        names["lead_source"]: (doc.get("leadSource") or "").strip(),
        names["tg_nickname"]: (doc.get("telegramUsername") or "").strip(),
        names["tg_id"]: str(doc.get("telegramId") or ""),
        names["semester"]: (doc.get("semester") or "").strip(),
        names["idp"]: "Так" if doc.get("isDisplaced") else "Ні",
        names["idp_region"]: (doc.get("displacedRegion") or "").strip(),
    }
    existing = {}
    for entry in pupil.get("customData") or []:
        name = (entry.get("name") or "").strip()
        if name and name not in existing:
            existing[name] = entry.get("value") or ""

    for name, value in values.items():
        if value and existing.get(name, "") != value:
            updates[name] = value

    if strict:
        # Повна заміна: у ШС лишається рівно те, що є у Firestore, плюс поля,
        # які веде школа. Усе інше зникає — так чистяться і застарілі значення,
        # і дублікати, яких у 213 карток по кілька на одне ім'я.
        keep = {names[alias] for alias in SCHOOL_OWNED}
        desired = {n: v for n, v in existing.items() if n in keep}
        desired.update({n: v for n, v in values.items() if v})

        has_duplicates = len(pupil.get("customData") or []) != len(existing)
        if desired != existing or has_duplicates:
            patch["customData"] = [{"name": n, "value": v} for n, v in desired.items()]
            updates = desired
    elif updates:
        # Масив замінюється цілком, тому зливаємо зі всім, що вже на картці —
        # інакше зникнуть «Ролі», які веде школа
        patch["customData"] = st.merge_custom_data(pupil.get("customData"), updates)

    return patch, updates


def parent_patch(doc: dict, parent: dict) -> dict:
    patch: dict = {}
    key = parent_key(parent["id"], doc.get("parentPhone") or "")
    if not (parent.get("externalID") or "").strip():
        patch["externalID"] = key

    # ШС вимагає непорожнє firstName. У 18 карток ми знаємо лише прізвище — там,
    # де замість імені стояло по батькові й ми його прибрали. Ламати наше
    # представлення заради чужого обмеження не варто, тож ПІБ таким карткам не
    # чіпаємо взагалі: у ШС воно лишається як було, зате ключ проставляється.
    if (doc.get("parentFirstName") or "").strip():
        for ours, theirs in (("parentFirstName", "firstName"),
                             ("parentLastName", "lastName")):
            value = (doc.get(ours) or "").strip()
            if value != (parent.get(theirs) or "").strip():
                patch[theirs] = value

    current = (parent.get("phoneNumber") or "").strip()
    phone = normalize_phone(doc.get("parentPhone"))
    # У ШС поле тримає кілька номерів через кому, а в нас лишився тільки перший:
    # normalize_phone відкидає решту при розборі. Записати його назад означало б
    # стерти запасні контакти, тому такі картки не чіпаємо.
    if phone and phone != current and "," not in current:
        patch["phoneNumber"] = phone

    return patch


async def main(argv: list[str] | None = None):
    """`argv=None` читає sys.argv як завжди (виклик з CLI-обгортки в scripts/);
    адмін-панель викликає з явним списком (напр. `["--apply"]`)."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--show", type=int, default=10)
    ap.add_argument("--strict", action="store_true",
                    help="повна заміна customData: у ШС лишається рівно те, що у Firestore")
    args = ap.parse_args(argv)

    registry = await st.get_registry()
    names = registry["field_name"]
    pupils = {p["id"]: p for p in await st.list_pupils()}
    parents = {p["id"]: p for p in await st.list_parents()}
    print(f"У ШС: {len(pupils)} учнів, {len(parents)} батьків")

    docs = []
    async for snap in db.collection("Svitlo").stream():
        data = snap.to_dict() or {}
        data["_id"] = snap.id
        docs.append(data)
    print(f"У Firestore: {len(docs)} документів\n")

    if args.limit:
        docs = docs[:args.limit]

    pupil_jobs, parent_jobs = [], []
    baseline_by_doc: dict[str, dict] = {}
    stats = collections.Counter()
    samples = collections.defaultdict(list)
    field_counts = collections.Counter()

    for doc in docs:
        st_id = doc.get("stPupilId")
        pupil = pupils.get(st_id) if st_id else None
        if not pupil:
            stats["учня немає у ШС"] += 1
            continue

        patch, custom_updates = await pupil_patch(doc, pupil, names, registry, args.strict)
        if patch:
            pupil_jobs.append((st_id, patch, doc))
            for field in patch:
                field_counts[f"учень: {field}"] += 1
                if len(samples[field]) < args.show and field != "customData":
                    samples[field].append(
                        (doc.get("firstName"), pupil.get(field), patch[field]))
            for name in sorted(custom_updates):
                field_counts[f"  customData: {name}"] += 1

        parent_id = doc.get("stParentId")
        parent = parents.get(parent_id) if parent_id else None
        p_patch = {}
        if parent:
            p_patch = parent_patch(doc, parent)
            if p_patch:
                parent_jobs.append((parent_id, p_patch, doc))
                for field in p_patch:
                    field_counts[f"батько: {field}"] += 1
                    if len(samples["p_" + field]) < args.show:
                        samples["p_" + field].append(
                            (doc.get("parentFirstName"), parent.get(field), p_patch[field]))
        elif doc.get("parentFirstName") or doc.get("parentLastName"):
            stats["батько є у нас, але не прив'язаний у ШС"] += 1

        baseline_by_doc[doc["_id"]] = synced_state(
            pupil, parent, names, patch, custom_updates, p_patch)

    print("=" * 74)
    print("ЩО ЗМІНИТЬСЯ")
    print("=" * 74)
    for field, count in sorted(field_counts.items()):
        print(f"  {count:>5}  {field}")

    print("\n" + "=" * 74)
    print("ПРИКЛАДИ")
    print("=" * 74)
    for key in ("externalID", "firstName", "lastName", "phoneNumber", "p_externalID",
                "p_firstName", "p_lastName", "p_phoneNumber"):
        if not samples[key]:
            continue
        print(f"\n  {key}")
        for who, was, now in samples[key][:5]:
            print(f"      {who}: {was!r} → {now!r}")

    print("\n" + "=" * 74)
    for key, value in stats.items():
        print(f"  {value:>5}  {key}")
    print(f"\nКарток учнів до оновлення:  {len(pupil_jobs)}")
    print(f"Карток батьків до оновлення: {len(parent_jobs)}")

    if not args.apply:
        print("\nПробний прогін. Щоб застосувати — додай --apply")
        return

    print("\nОновлюю картки учнів…")
    errors = []
    for index, (st_id, patch, doc) in enumerate(pupil_jobs, 1):
        try:
            await st.update_pupil(st_id, patch)
        except st.STError as exc:
            errors.append(("учень", st_id, doc.get("_id"), exc))
        if index % 100 == 0:
            print(f"  {index}/{len(pupil_jobs)}")
    print(f"  {len(pupil_jobs)}/{len(pupil_jobs)}")

    print("Оновлюю картки батьків…")
    for index, (parent_id, patch, doc) in enumerate(parent_jobs, 1):
        try:
            await st.update_parent(parent_id, patch)
        except st.STError as exc:
            errors.append(("батько", parent_id, doc.get("_id"), exc))
        if index % 100 == 0:
            print(f"  {index}/{len(parent_jobs)}")
    print(f"  {len(parent_jobs)}/{len(parent_jobs)}")

    # Фіксуємо, що саме тепер лежить у ШС з нашого боку. Це baseline для
    # drift-репорту: пізніша відмінність = хтось поправив картку руками.
    failed_docs = {doc_id for _, _, doc_id, _ in errors}
    now = datetime.now(timezone.utc).isoformat()
    recorded = 0
    to_record = [d for d in docs
                 if d["_id"] in baseline_by_doc and d["_id"] not in failed_docs]
    for start in range(0, len(to_record), BATCH_SIZE):
        batch = db.batch()
        for doc in to_record[start:start + BATCH_SIZE]:
            batch.set(db.collection(SYNC_STATE).document(doc["_id"]),
                      {"at": now, "values": baseline_by_doc[doc["_id"]]})
        await batch.commit()
        recorded += len(to_record[start:start + BATCH_SIZE])
    print(f"\nЗафіксовано стан синхронізації: {recorded} документів")

    if errors:
        print(f"\n⚠ ПОМИЛОК: {len(errors)}")
        for kind, st_id, doc_id, exc in errors[:20]:
            print(f"  {kind} #{st_id} ({doc_id}): {exc.status} {exc.codes} {exc.keys}")
    else:
        print("\nПомилок немає.")
