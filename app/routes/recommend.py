"""選課建議路由"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.services.session_service import get_display_name, is_logged_in
from app.templates_config import render_template

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def recommend_page(request: Request):
    """選課建議頁面"""
    if not is_logged_in(request):
        return RedirectResponse("/login", status_code=303)

    return render_template(
        "recommend.html",
        {"request": request, "title": "選課建議", "logged_in": True, "display_name": get_display_name(request)},
    )