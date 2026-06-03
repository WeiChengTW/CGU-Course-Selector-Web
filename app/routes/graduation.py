"""畢業進度路由"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.services.graduation_service import GraduationService, run_graduation_analysis
from app.services.session_service import get_session_dir, is_logged_in
from app.templates_config import render_template

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def graduation_page(request: Request):
    if not is_logged_in(request):
        return RedirectResponse("/login", status_code=303)

    session_dir = get_session_dir(request)
    svc = GraduationService(session_dir)
    status = svc.get_status()
    report = svc.get_report() if status.get("status") == "done" else None

    return render_template(
        "graduation.html",
        {
            "request": request,
            "title": "畢業進度",
            "logged_in": True,
            "analysis_status": status,
            "report": report,
        },
    )


@router.post("/analyze", response_class=HTMLResponse)
async def start_analysis(
    request: Request,
    background_tasks: BackgroundTasks,
    grad_pdf: UploadFile = File(...),
    honor_program: str = Form(""),
    api_key: str = Form(""),
    honor_pdf: UploadFile = File(None),
):
    if not is_logged_in(request):
        return RedirectResponse("/login", status_code=303)

    session_dir = get_session_dir(request)
    svc = GraduationService(session_dir)

    # Save uploaded PDFs
    pdf_bytes = await grad_pdf.read()
    if not pdf_bytes:
        return render_template(
            "graduation.html",
            {
                "request": request,
                "title": "畢業進度",
                "logged_in": True,
                "analysis_status": {"status": "error", "message": "請上傳畢業學分 PDF 檔案"},
                "report": None,
            },
        )

    grad_pdf_path = session_dir / "graduation_pdf.pdf"
    grad_pdf_path.write_bytes(pdf_bytes)

    if is_honor and honor_pdf and honor_pdf.filename:
        honor_bytes = await honor_pdf.read()
        if honor_bytes:
            honor_pdf_path = session_dir / "graduation_honor_pdf.pdf"
            honor_pdf_path.write_bytes(honor_bytes)

    is_honor = honor_program.lower() in ("true", "on", "1", "yes")
    effective_api_key = api_key.strip() or None
    svc.write_status("analyzing", "任務已排入，準備開始分析...")

    background_tasks.add_task(
        run_graduation_analysis,
        session_dir=session_dir,
        honor_program=is_honor,
        api_key=effective_api_key,
    )

    return RedirectResponse("/graduation", status_code=303)


@router.get("/status", response_class=HTMLResponse)
async def get_status(request: Request):
    """HTMX polling endpoint — returns status partial."""
    if not is_logged_in(request):
        return HTMLResponse("")

    session_dir = get_session_dir(request)
    svc = GraduationService(session_dir)
    status = svc.get_status()
    report = svc.get_report() if status.get("status") == "done" else None

    return render_template(
        "graduation_status_partial.html",
        {
            "request": request,
            "analysis_status": status,
            "report": report,
        },
    )


@router.post("/reset")
async def reset_analysis(request: Request):
    if not is_logged_in(request):
        return RedirectResponse("/login", status_code=303)

    session_dir = get_session_dir(request)
    GraduationService(session_dir).reset()
    return RedirectResponse("/graduation", status_code=303)


@router.get("/data", response_class=JSONResponse)
async def get_graduation_data(request: Request):
    """JSON API for the existing Alpine.js dashboard (backwards compat)."""
    session_dir = get_session_dir(request)
    if session_dir is None:
        return JSONResponse({"error": "請先登入"}, status_code=401)

    from app.services.course_service import CourseService

    svc = GraduationService(session_dir)
    report = svc.get_report()
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
