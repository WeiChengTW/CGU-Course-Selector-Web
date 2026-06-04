from __future__ import annotations

import csv
from pathlib import Path

from app.config import get_logger
from lib.icgu_scraper import BOOKING_FIELDS, COURSE_FIELDS, EXEMPTION_FIELDS, approved_exemption_credits
from lib.catalog import write_details

logger = get_logger(__name__)

DETAIL_FIELDS = ["學年學期", "科目代號", "開課序號", "開課單位", "年級", "課程名稱", "授課教師", "學分", "上課時間", "課程類別"]


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})
    tmp_path.replace(path)


def _detail_rows(courses: list[dict[str, str]]) -> list[dict[str, str]]:
    """Fallback detail rows when catalog query fails — match OUTPUT_COLUMNS format."""
    from app.services.catalog_service import CatalogService, TERM_IDS

    rows = []
    for row in courses:
        sem = row.get("學年學期", "")
        year = int(sem[:3]) if len(sem) >= 3 else 0
        term = int(sem[3:]) if len(sem) >= 4 else 0
        termid = TERM_IDS.get((year, term))

        category = ""
        # Try catalog lookup to fill 課程類別
        if termid:
            try:
                sectionid = row.get("sectionid") or row.get("開課序號", "")
                call_id = row.get("call_id") or row.get("科目代號", "")
                name = row.get("課程名稱", "")
                if sectionid:
                    matches = CatalogService.search_courses(termid=termid, sectionid=sectionid)
                elif call_id:
                    matches = CatalogService.search_courses(termid=termid, call_id=call_id)
                elif name:
                    matches = CatalogService.search_courses(termid=termid, cName=name)
                else:
                    matches = []
                if matches:
                    category = matches[0].get("CLASSIFICATIONCATNAME", "")
            except Exception:
                pass

        rows.append({
            "學年學期": sem,
            "科目代號": row.get("call_id") or row.get("科目代號", ""),
            "開課序號": row.get("sectionid") or row.get("開課序號", ""),
            "開課單位": "",
            "年級": "",
            "課程名稱": row.get("課程名稱", ""),
            "授課教師": "",
            "學分": row.get("學分數", ""),
            "上課時間": "",
            "課程類別": category,
        })
    return rows


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
        logger.warning("catalog_detail_query_failed", error=str(e))
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
        logger.info("icgu_sync_headless_attempt")
        records = run_icgu_sync_subprocess(session_dir, headless=True)
    except ConnectionAbortedError:
        logger.warning("icgu_sync_headless_failed", reason="快取已過期或不存在")
        records = run_icgu_sync_subprocess(session_dir, headless=False)

    return write_icgu_sync_files(
        session_dir=session_dir,
        courses=records["courses"],
        exemptions=records["exemptions"],
        errors=records["errors"],
        booking_courses=records.get("booking_courses", []),
        profile=records.get("profile", {}),
    )
