from __future__ import annotations

import csv
from pathlib import Path

from lib.icgu_scraper import BOOKING_FIELDS, COURSE_FIELDS, EXEMPTION_FIELDS, approved_exemption_credits
from lib.catalog import write_details

DETAIL_FIELDS = ["學年學期", "課程名稱", "學分", "課程類別"]


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})
    tmp_path.replace(path)


def _detail_rows(courses: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {
            "學年學期": row.get("學年學期", ""),
            "課程名稱": row.get("課程名稱", ""),
            "學分": row.get("學分數", ""),
            "課程類別": "",
        }
        for row in courses
    ]


def write_icgu_sync_files(
    session_dir: Path,
    courses: list[dict[str, str]],
    exemptions: list[dict[str, str]],
    errors: list[str],
    booking_courses: list[dict[str, str]] | None = None,
    profile: dict | None = None,
) -> dict:
    _write_csv(session_dir / "taken_courses.csv", COURSE_FIELDS, courses)

    query_list = []
    for c in courses:
        sem = c.get("學年學期", "")
        year = sem[:3] if len(sem) >= 3 else ""
        term = sem[3:] if len(sem) >= 4 else ""
        query_list.append({
            "year": year,
            "term": term,
            "call_id": c.get("call_id") or "",
            "sectionid": c.get("sectionid") or "",
            "name": c.get("課程名稱", "")
        })

    try:
        catalog_count, total_credits, cat_errors = write_details(
            query_list,
            session_dir / "courses_detail.csv",
            delay=0.1
        )
        if cat_errors:
            errors.extend(cat_errors)
    except Exception as e:
        print(f"查詢課程目錄詳細資料失敗：{e}")
        _write_csv(session_dir / "courses_detail.csv", DETAIL_FIELDS, _detail_rows(courses))
        errors.append(f"課程目錄查詢失敗: {e}")

    _write_csv(session_dir / "icgu_exemptions.csv", EXEMPTION_FIELDS, exemptions)

    if booking_courses:
        _write_csv(session_dir / "icgu_booking.csv", BOOKING_FIELDS, booking_courses)

    status = "success"
    if errors and courses:
        status = "partial"
    elif errors:
        status = "error"

    result: dict = {
        "status": status,
        "courses_count": len(courses),
        "exemptions_count": len(exemptions),
        "booking_count": len(booking_courses) if booking_courses else 0,
        "approved_exemption_credits": approved_exemption_credits(exemptions),
        "errors": errors,
    }
    if profile:
        result.update(profile)
    return result


def sync_icgu_courses(session_dir: Path) -> dict:
    from lib.icgu_auth import run_icgu_sync_subprocess

    try:
        print("嘗試在背景執行成績與課程同步...")
        records = run_icgu_sync_subprocess(session_dir, headless=True)
    except ConnectionAbortedError:
        print("背景同步失敗（快取已過期或不存在），啟動視窗進行手動登入...")
        records = run_icgu_sync_subprocess(session_dir, headless=False)

    return write_icgu_sync_files(
        session_dir=session_dir,
        courses=records["courses"],
        exemptions=records["exemptions"],
        errors=records["errors"],
        booking_courses=records.get("booking_courses", []),
        profile=records.get("profile", {}),
    )
