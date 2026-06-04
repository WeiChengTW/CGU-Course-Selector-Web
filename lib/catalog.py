from __future__ import annotations

import csv
import time
import httpx
from pathlib import Path

from app.config import get_logger
from lib.scraper import read_courses
from lib.utils import ensure_parent

logger = get_logger(__name__)

CATALOG_API = "https://catalog.cgu.edu.tw/IsService/api/Course/GetCourseSections"

TERM_IDS = {
    (112, 1): 63,
    (112, 2): 64,
    (112, 3): 65,
    (113, 1): 66,
    (113, 2): 67,
    (113, 3): 68,
    (114, 1): 69,
    (114, 2): 70,
    (114, 3): 71,
    (115, 1): 72,
}

OUTPUT_COLUMNS = [
    "學年學期",
    "科目代號",
    "開課序號",
    "開課單位",
    "年級",
    "課程名稱",
    "授課教師",
    "學分",
    "上課時間",
    "課程類別",
]


def term_id_for(year: str, term: str, term_map: dict | None = None) -> int:
    key = (int(year), int(term))
    if key in TERM_IDS:
        return TERM_IDS[key]
    if term_map:
        key_str = f"{year}-{term}"
        if key_str in term_map:
            return term_map[key_str]
    raise ValueError(
        f"找不到學年學期 {year}-{term} 對應的 termid，請更新 TERM_IDS 或是提供 --term-map JSON。"
    )


def fetch_course(termid: int, sectionid: str = "", call_id: str = "", name: str = "") -> dict:
    params = {
        "termid": str(termid),
        "departmentid": "",
        "call_id": call_id,
        "keyward": "",
        "sectionid": sectionid,
        "teaName": "",
        "cName": name,
        "year": "",
        "fieldid": "",
        "week": "",
        "stime": "",
        "etime": "",
    }
    with httpx.Client(timeout=20.0) as client:
        response = client.get(CATALOG_API, params=params, headers={"User-Agent": "Mozilla/5.0"})
        payload = response.json()

    if not payload:
        # Fallback: search by name if initial query returned nothing
        if name and not sectionid and not call_id:
            params_fb = {
                "termid": str(termid),
                "departmentid": "",
                "call_id": "",
                "keyward": "",
                "sectionid": "",
                "teaName": "",
                "cName": name,
                "year": "",
                "fieldid": "",
                "week": "",
                "stime": "",
                "etime": "",
            }
            with httpx.Client(timeout=20.0) as client:
                response = client.get(CATALOG_API, params=params_fb, headers={"User-Agent": "Mozilla/5.0"})
                payload = response.json()
            if not payload:
                raise LookupError(f"查無資料：termid={termid}, name={name}")
    if isinstance(payload, dict):
        payload = [payload]

    if sectionid:
        exact_matches = [
            item
            for item in payload
            if str(item.get("SECTIONID", "")).strip() == str(sectionid).strip()
        ]
    else:
        exact_matches = [
            item
            for item in payload
            if str(item.get("CALL_ID", "")).strip() == str(call_id).strip()
        ]
        if not exact_matches:
            exact_matches = payload

    if not exact_matches:
        raise LookupError(
            f"API 回傳資料中找不到精準項目：termid={termid}, sectionid={sectionid}, call_id={call_id}"
        )
    if len(exact_matches) > 1:
        logger.warning("multiple_api_matches", termid=termid, sectionid=sectionid)
    return exact_matches[0]


def detail_row(course: dict[str, str], data: dict) -> list:
    return [
        f"{data.get('ACADMICYEAR', course['year'])}-{data.get('ACADMICTERM', course['term'])}",
        data.get("CALL_ID", course.get("call_id", "")),
        data.get("SECTIONID", course.get("sectionid", "")),
        data.get("DEPARTMENTNAME_C", ""),
        data.get("YEAR", ""),
        data.get("CCOURSENAME", course.get("name", "")),
        data.get("NAME", ""),
        data.get("CREDITS", ""),
        data.get("C_PTIME", ""),
        data.get("CLASSIFICATIONCATNAME", ""),
    ]


def write_details(
    courses: list[dict[str, str]],
    output_path: Path,
    delay: float,
    term_map: dict | None = None,
) -> tuple[int, float, list[str]]:
    if not courses:
        raise ValueError("沒有課程可查詢。")

    rows = []
    errors = []
    total_credits = 0.0

    for index, course in enumerate(courses, start=1):
        c_id = course.get("sectionid") or course.get("call_id") or ""
        label = (
            f"{course['year']}-{course['term']} {course['name']} {c_id}"
        )
        try:
            termid = term_id_for(course["year"], course["term"], term_map)
            data = fetch_course(termid, sectionid=course.get("sectionid", ""), call_id=course.get("call_id", ""), name=course.get("name", ""))

            api_name = data.get("CCOURSENAME", "")
            if (
                api_name
                and course.get("name")
                and course["name"].lower() not in api_name.lower()
                and api_name.lower() not in course["name"].lower()
            ):
                logger.warning("course_name_mismatch", expected=course['name'], api=api_name)

            rows.append(detail_row(course, data))
            total_credits += float(data.get("CREDITS") or 0)
            logger.info("catalog_query_ok", index=index, total=len(courses), label=label)
        except Exception as exc:
            errors.append(f"{label}: {exc}")
            logger.error("catalog_query_failed", index=index, total=len(courses), label=label, error=str(exc))
        if delay and index < len(courses):
            time.sleep(delay)

    ensure_parent(output_path)
    with output_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(OUTPUT_COLUMNS)
        writer.writerows(rows)

    return len(rows), total_credits, errors


def generate(
    input_path: Path, output_path: Path, delay: float, term_map: dict | None = None
) -> tuple[int, float, list[str]]:
    courses = read_courses(input_path)
    if not courses:
        raise ValueError(f"{input_path} 沒有解析到任何課程。")
    return write_details(courses, output_path, delay, term_map)
