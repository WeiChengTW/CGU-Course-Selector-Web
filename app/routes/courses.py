"""已修課程路由"""

import asyncio

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.services.course_service import CourseService
from app.services.moocs_sync_service import sync_moocs_courses
from app.services.session_service import (
    get_session_dir,
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

    return render_template(
        "courses.html",
        {"request": request, "title": "已修課程", "logged_in": True},
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
        "message": "已重新同步 MOOCS 課程紀錄",
        "courses": courses,
        "last_synced_at": updated_meta.get("last_synced_at", ""),
    }