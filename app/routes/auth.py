from __future__ import annotations

import asyncio

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.services.moocs_sync_service import sync_moocs_courses
from app.services.session_service import (
    SESSION_COOKIE,
    create_session_dir,
    destroy_session,
    get_session_id,
    is_logged_in,
    restore_course_record,
    save_course_record,
    save_session_meta,
)
from app.templates_config import render_template

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if is_logged_in(request):
        return RedirectResponse("/courses", status_code=303)

    return render_template(
        "login.html",
        {
            "request": request,
            "title": "登入",
            "error": "",
            "logged_in": False,
        },
    )


@router.post("/login", response_class=HTMLResponse)
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    session_id, session_dir = create_session_dir()

    username = username.strip()

    try:
        saved_meta = restore_course_record(username, session_dir)
        if saved_meta is not None:
            save_session_meta(
                session_dir,
                username,
                saved_meta.get("last_sync_result"),
                saved_meta.get("last_synced_at"),
            )
        else:
            sync_result = await asyncio.to_thread(
                sync_moocs_courses,
                username=username,
                password=password,
                session_dir=session_dir,
            )
            display_name = sync_result.get("display_name") or username
            save_course_record(username, session_dir, sync_result)
            save_session_meta(session_dir, display_name, sync_result)
    except Exception:
        destroy_session(session_id)
        return render_template(
            "login.html",
            {
                "request": request,
                "title": "登入",
                "error": "登入或同步失敗，請確認帳密正確，或單一登入/M365 驗證是否逾時或取消。",
                "logged_in": False,
            },
        )

    response = RedirectResponse("/courses", status_code=303)
    response.set_cookie(
        SESSION_COOKIE,
        session_id,
        httponly=True,
        samesite="lax",
        max_age=4 * 60 * 60,
    )
    return response


@router.post("/login/icgu", response_class=HTMLResponse)
async def login_icgu(request: Request):
    from app.services.icgu_sync_service import sync_icgu_courses

    session_id, session_dir = create_session_dir()

    try:
        sync_result = await asyncio.to_thread(sync_icgu_courses, session_dir)
        display_name = sync_result.get("display_name") or "iCGU 使用者"
        save_session_meta(session_dir, display_name, sync_result)
    except Exception as exc:
        destroy_session(session_id)
        return render_template(
            "login.html",
            {
                "request": request,
                "title": "登入",
                "error": f"iCGU 登入或同步失敗：{exc}",
                "logged_in": False,
            },
        )

    response = RedirectResponse("/courses", status_code=303)
    response.set_cookie(
        SESSION_COOKIE,
        session_id,
        httponly=True,
        samesite="lax",
        max_age=4 * 60 * 60,
    )
    return response


@router.post("/logout")
async def logout(request: Request):
    session_id = get_session_id(request)
    destroy_session(session_id)

    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response
