"""畢業進度路由"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.services.course_service import CourseService
from app.services.graduation_service import GraduationService
from app.services.session_service import get_session_dir, is_logged_in
from app.templates_config import render_template

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def graduation_page(request: Request):
    """畢業進度頁面"""
    if not is_logged_in(request):
        return RedirectResponse("/login", status_code=303)

    return render_template(
        "graduation.html",
        {"request": request, "title": "畢業進度", "logged_in": True},
    )


@router.get("/data", response_class=JSONResponse)
async def get_graduation_data(request: Request):
    """取得畢業報告資料 (API)"""
    session_dir = get_session_dir(request)
    if session_dir is None:
        return JSONResponse({"error": "請先登入"}, status_code=401)

    report = GraduationService(session_dir).get_report()
    if report is None:
        course_info = CourseService(session_dir).get_taken_courses_info()
        recognized_credits = course_info["passed_credits"]
        required_credits = 128
        missing_credits = max(0, required_credits - recognized_credits)
        return {
            "status": "尚未分析畢業規則",
            "recognized_credits": recognized_credits,
            "required_credits": required_credits,
            "missing_credits": missing_credits,
            "one_sentence_summary": f"已通過 {recognized_credits:g} 學分，尚需 {missing_credits:g} 學分；細項仍需畢業規則分析。",
            "requirements": [],
            "missing_items": [],
            "manual_review_items": [],
            "next_semester_recommendations": [],
        }
    return report