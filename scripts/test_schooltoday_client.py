"""Перевірка клієнта SchoolToday без жодного запису.

Читає довідники, шукає по externalID, будує payload для вигаданого документа
Firestore і показує, що саме пішло б у ШС.

    python -m scripts.test_schooltoday_client
"""
import asyncio
import json
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

from core import schooltoday as st  # noqa: E402  (після load_dotenv)

sys.stdout.reconfigure(encoding="utf-8")

DOC_ID = "SV-260823-testdoc"
DOC = {
    "firstName": "Olesia", "lastName": "Merkulova",
    "email": "Olesia.Merkulova@Gmail.com  ",
    "phone": "0671234567",
    "gender": "Female",
    "birthDate": datetime(2010, 10, 20, 12, tzinfo=timezone.utc),
    "ageGroup": "older",
    "country": "Україна", "city": "Київ",
    "isDisplaced": True, "displacedRegion": "Донецька область",
    "parentFirstName": "Світлана", "parentLastName": "Меркулова",
    "parentEmail": "s.merkulova@gmail.com", "parentPhone": "978815630",
    "leadSource": "Instagram",
    "hasHealthIssues": False, "healthIssuesDetails": "",
    "house": "Newbie", "semester": "25-26_06",
    "telegramId": 384756291, "telegramUsername": "olesia_m",
}


def show(title, value):
    print(f"\n{'=' * 68}\n{title}\n{'=' * 68}")
    print(json.dumps(value, ensure_ascii=False, indent=2) if isinstance(value, (dict, list)) else value)


async def main():
    registry = await st.get_registry()
    show("ДОВІДНИКИ", {
        "поля": registry["field_name"],
        "класи": registry["class_id"],
        "типи учня": registry["pupil_type_id"],
    })

    show("PAYLOAD УЧНЯ (нова картка)",
         await st.build_pupil_payload(DOC_ID, DOC, grant_access=True))

    ext = st.parent_external_id(DOC)
    show("КЛЮЧ БАТЬКА", f"{DOC['parentPhone']!r} -> {ext}")
    show("PAYLOAD БАТЬКА", st.build_parent_payload(DOC, ext))

    print(f"\n{'=' * 68}\nПЕРЕВІРКИ\n{'=' * 68}")

    parent_payload = st.build_parent_payload(DOC, ext, grant_access=True)
    assert "pupilIDs" not in parent_payload, "pupilIDs не має бути в payload батька"
    print("  OK  payload батька не містить pupilIDs")

    # «Довільне поле школи» — назва, якої немає в наших FIELD_IDS: так само
    # виглядає будь-яке поле, що завела школа й ведемо не ми. Має вціліти.
    existing = [
        {"name": registry["field_name"]["roles"], "value": "SCL;BUDDY"},
        {"name": "Довільне поле школи", "value": "Cambria"},
        {"name": registry["field_name"]["semester"], "value": "00-01_01"},
        {"name": registry["field_name"]["semester"], "value": "00-01_01"},
    ]
    merged = st.merge_custom_data(existing, await st.build_pupil_custom_data(DOC))
    names = [e["name"] for e in merged]
    roles = next(e for e in merged if e["name"] == registry["field_name"]["roles"])
    assert roles["value"] == "SCL;BUDDY", "ролі мають вціліти"
    school_own = next(e for e in merged if e["name"] == "Довільне поле школи")
    assert school_own["value"] == "Cambria", "чуже поле школи має вціліти"
    assert len(names) == len(set(names)), "дублікати мають схлопнутись"
    semester = next(e for e in merged if e["name"] == registry["field_name"]["semester"])
    assert semester["value"] == DOC["semester"], "наше значення має перекрити старе"
    print("  OK  merge_custom_data зберіг «Ролі» і чуже поле школи, схлопнув дублі,")
    print("      перезаписав «Семестр зарахування» на наше значення")

    payload = await st.build_pupil_payload(DOC_ID, DOC)
    assert "parentIDs" not in payload, "parentIDs не має з'являтись без потреби"
    print("  OK  без parent_ids ключ parentIDs у payload відсутній")

    assert payload["phoneNumber"] == "+380671234567", "телефон учня має нормалізуватись і потрапляти в payload"
    print("  OK  телефон учня нормалізується і потрапляє в payload")

    for raw, expect in [("978815630", "P-380978815630"), ("+38068823020", None), ("", None)]:
        got = st.parent_external_id({"parentPhone": raw})
        assert got == expect, f"{raw!r} -> {got}, очікували {expect}"
    print("  OK  ключ батька: лікування працює, обрізані номери відхиляються")

    for raw in ["olesia_m", "@olesia_m", "  @olesia_m  "]:
        assert st.normalize_nickname(raw) == "olesia_m"
    print("  OK  нікнейм зводиться до одного формату")

    blank = dict(DOC, healthIssuesDetails="", displacedRegion="", leadSource="")
    custom = await st.build_pupil_custom_data(blank)
    assert registry["field_name"]["health_details"] not in custom
    assert registry["field_name"]["idp_region"] not in custom
    assert registry["field_name"]["health"] in custom, "«Так/Ні» завжди має значення"
    print("  OK  порожні значення не потрапляють у payload і не затирають дані школи")

    kept = st.merge_custom_data(
        [{"name": registry["field_name"]["health_details"], "value": "алергія"}], custom
    )
    detail = next(e for e in kept if e["name"] == registry["field_name"]["health_details"])
    assert detail["value"] == "алергія", "існуюче значення має вціліти"
    print("  OK  наявний текст школи переживає запис із порожнім полем")

    print(f"\n{'=' * 68}\nЖИВІ ЗАПИТИ (лише читання)\n{'=' * 68}")
    print(f"  find_pupil('{DOC_ID}')  -> {await st.find_pupil(DOC_ID)}")
    print(f"  find_parent('{ext}')    -> {await st.find_parent(ext)}")

    active = await st.list_pupils(is_hidden=False)
    hidden = await st.list_pupils(is_hidden=True)
    parents = await st.list_parents()
    print(f"  активних учнів {len(active)} · деактивованих {len(hidden)} · батьків {len(parents)}")

    real = next((p for p in active if p.get("parentIDs")), None)
    if real:
        fetched = await st.get_pupil(real["id"])
        print(f"  get_pupil({real['id']}) -> {fetched['fullName']!r}, "
              f"батьки {fetched.get('parentIDs')}")

    print("\nУсі перевірки пройдено. Жодного запису не виконано.")


if __name__ == "__main__":
    asyncio.run(main())
