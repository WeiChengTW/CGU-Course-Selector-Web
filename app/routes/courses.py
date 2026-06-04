"""已修課程路由"""

import asyncio

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.services.catalog_service import CatalogService
from app.services.course_service import CourseService
from app.services.moocs_sync_service import sync_moocs_courses
from app.services.session_service import (
    get_display_name,
    get_session_dir,
    get_session_profile,
    is_logged_in,
    load_session_meta,
    save_course_record,
    update_session_sync_meta,
)
from app.templates_config import render_template

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def courses_page(request: Request):
    """已修課程頁面"""
    if not is_logged_in(request):
        return RedirectResponse("/login", status_code=303)

    profile = get_session_profile(request)
    return render_template(
        "courses.html",
        {
            "request": request,
            "title": "已修課程",
            "logged_in": True,
            "display_name": profile.get("display_name", ""),
            "booking_count": profile.get("booking_count", 0),
        },
    )


@router.get("/data", response_class=JSONResponse)
async def get_courses_data(request: Request):
    """取得已修課程資料 (API)"""
    session_dir = get_session_dir(request)
    if session_dir is None:
        return JSONResponse({"error": "請先登入"}, status_code=401)

    courses = CourseService(session_dir).get_courses()
    meta = load_session_meta(session_dir)
    return {"courses": courses, "last_synced_at": meta.get("last_synced_at", "")}


@router.post("/refresh", response_class=JSONResponse)
async def refresh_courses(request: Request, password: str = Form(...)):
    session_dir = get_session_dir(request)
    if session_dir is None:
        return JSONResponse({"error": "請先登入"}, status_code=401)

    meta = load_session_meta(session_dir)
    username = (meta.get("username") or "").strip()
    if not username:
        return JSONResponse({"error": "找不到登入帳號紀錄，請重新登入後再刷新"}, status_code=400)

    try:
        sync_result = await asyncio.to_thread(
            sync_moocs_courses,
            username=username,
            password=password,
            session_dir=session_dir,
        )
    except Exception as exc:
        return JSONResponse({"error": f"同步失敗：{str(exc)[:200]}"}, status_code=400)

    save_course_record(username, session_dir, sync_result)
    updated_meta = update_session_sync_meta(session_dir, sync_result)
    courses = CourseService(session_dir).get_courses()
    return {
        "ok": True,
        "message": "已重新同步校務成績紀錄",
        "courses": courses,
        "last_synced_at": updated_meta.get("last_synced_at", ""),
    }


@router.post("/import-booking", response_class=JSONResponse)
async def import_booking(request: Request):
    import csv

    session_dir = get_session_dir(request)
    if session_dir is None:
        return JSONResponse({"error": "請先登入"}, status_code=401)

    booking_path = session_dir / "icgu_booking.csv"
    if not booking_path.exists():
        return JSONResponse({"error": "找不到預選課程資料"}, status_code=404)

    course_service = CourseService(session_dir)
    booking_rows = []
    booking_names = set()
    with booking_path.open("r", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            name = row.get("課程名稱", "").strip()
            section_id = row.get("開課序號", "").strip()
            if not name and not section_id:
                continue
            booking_names.add(name)

            course = None
            if section_id:
                try:
                    matches = CatalogService.search_courses(termid=72, sectionid=section_id)
                    course = next(
                        (item for item in matches if str(item.get("SECTIONID", "")).strip() == section_id),
                        matches[0] if matches else None,
                    )
                except Exception:
                    course = None

            if course is None and name:
                try:
                    matches = CatalogService.search_courses(termid=72, cName=name)
                    course = next(
                        (item for item in matches if item.get("CCOURSENAME", "").strip() == name),
                        matches[0] if matches else None,
                    )
                except Exception:
                    course = None

            if course:
                course_name = course.get("CCOURSENAME", "")
                status_info = course_service.check_course_status(course_name)
                course["course_status"] = status_info["status"]
                course["course_score"] = status_info.get("score")
                booking_rows.append(course)
            else:
                booking_rows.append({
                    "SECTIONID": section_id or name,
                    "CCOURSENAME": name,
                    "CREDITS": row.get("學分數", ""),
                    "DEPARTMENTNAME_C": row.get("開課單位", ""),
                    "C_PTIME": "",
                    "NAME": "",
                    "course_status": "not_taken",
                    "course_score": None,
                })

    taken_path = session_dir / "taken_courses.csv"
    if taken_path.exists() and booking_names:
        with taken_path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or ["學年學期", "課程名稱", "學分數", "修課成績"]
            taken_rows = [
                row for row in reader
                if not (
                    row.get("修課成績", "").strip() == "預選"
                    and row.get("課程名稱", "").strip() in booking_names
                )
            ]
        with taken_path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(taken_rows)

    return {"imported": len(booking_rows), "courses": booking_rows}