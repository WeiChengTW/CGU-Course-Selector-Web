"""已修課程路由"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.services.course_service import CourseService
from app.services.session_service import get_session_dir, is_logged_in
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
    return courses