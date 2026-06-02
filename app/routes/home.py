"""首頁路由"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.services.session_service import is_logged_in
from app.templates_config import render_template

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """首頁"""
    return render_template(
        "index.html",
        {"request": request, "title": "長庚大學選課系統", "logged_in": is_logged_in(request)},
    )