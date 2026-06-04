"""開課查詢路由"""

from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from app.services.catalog_service import CatalogService
from app.services.course_service import CourseService
from app.services.session_service import get_display_name, get_session_dir, get_session_profile, is_logged_in
from app.templates_config import render_template

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def catalog_page(request: Request):
    """開課查詢頁面"""
    if not is_logged_in(request):
        return RedirectResponse("/login", status_code=303)

    profile = get_session_profile(request)
    return render_template(
        "catalog.html",
        {
            "request": request,
            "title": "課程預選",
            "logged_in": True,
            "display_name": get_display_name(request),
            "booking_count": profile.get("booking_count", 0),
        },
    )


@router.get("/search", response_class=JSONResponse)
async def search_courses(
    request: Request,
    termid: int = Query(..., description="開課學期代碼"),
    departmentid: str = Query("", description="開課單位"),
    keyward: str = Query("", description="關鍵字"),
    sectionid: str = Query("", description="開課序號"),
    call_id: str = Query("", description="科目代號"),
    teaName: str = Query("", description="授課教師"),
    cName: str = Query("", description="課程名稱"),
    year: str = Query("", description="年級"),
    fieldid: str = Query("", description="通識領域"),
    week: str = Query("", description="上課星期"),
    stime: str = Query("", description="開始節次"),
    etime: str = Query("", description="結束節次"),
    lang: str = Query("", description="授課語言"),
):
    """多條件搜尋課程 API，並標記已修狀態"""
    session_dir = get_session_dir(request)
    if session_dir is None:
        return JSONResponse({"error": "請先登入"}, status_code=401)

    course_service = CourseService(session_dir)

    try:
        course_name = cName or keyward
        results = CatalogService.search_courses(
            termid=termid,
            departmentid=departmentid,
            keyward=keyward,
            sectionid=sectionid,
            call_id=call_id,
            teaName=teaName,
            cName=course_name,
            year=year,
            fieldid=fieldid,
            week=week,
            stime=stime,
            etime=etime,
            lang=lang,
        )

        # 標記已修狀態（使用新的 check_course_status）
        for course in results:
            course_name = course.get("CCOURSENAME", "")
            status_info = course_service.check_course_status(course_name)
            course["course_status"] = status_info["status"]
            course["course_score"] = status_info.get("score")

        return results
    except Exception as e:
        return {"error": str(e)}


@router.get("/departments", response_class=JSONResponse)
async def get_departments(termid: int):
    """取得開課單位清單"""
    try:
        return CatalogService.get_departments(termid)
    except Exception:
        return []


@router.get("/taken-courses", response_class=JSONResponse)
async def get_taken_courses(request: Request):
    """取得已修課程資訊"""
    session_dir = get_session_dir(request)
    if session_dir is None:
        return JSONResponse({"error": "請先登入"}, status_code=401)

    return CourseService(session_dir).get_taken_courses_info()