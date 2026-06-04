from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi_csrf_protect import CsrfProtect

from app.config import get_logger
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

logger = get_logger(__name__)
router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, csrf_protect: CsrfProtect = Depends()):
    if is_logged_in(request):
        return RedirectResponse("/courses", status_code=303)

    # 生成 CSRF token
    csrf_token, signed_token = csrf_protect.generate_csrf_tokens()

    response = render_template(
        "login.html",
        {
            "request": request,
            "title": "登入",
            "error": "",
            "logged_in": False,
            "csrf_token": csrf_token,
        },
    )

    # 設置 CSRF cookie
    csrf_protect.set_csrf_cookie(signed_token, response)
    return response


@router.post("/login", response_class=HTMLResponse)
async def login(
    request: Request,
    csrf_protect: CsrfProtect = Depends(),
    username: str = Form(...),
    password: str = Form(...),
):
    # 驗證 CSRF token
    await csrf_protect.validate_csrf(request)

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
            logger.info("login_success", username=username, method="moocs", restored=True)
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
            logger.info("login_success", username=username, method="moocs", restored=False)
    except Exception as e:
        destroy_session(session_id)
        logger.error("login_failed", username=username, method="moocs", error=str(e))

        # 重新生成 CSRF token 給錯誤頁面
        csrf_token, signed_token = csrf_protect.generate_csrf_tokens()
        response = render_template(
            "login.html",
            {
                "request": request,
                "title": "登入",
                "error": "登入或同步失敗，請確認帳密正確，或單一登入/M365 驗證是否逾時或取消。",
                "logged_in": False,
                "csrf_token": csrf_token,
            },
        )
        csrf_protect.set_csrf_cookie(signed_token, response)
        return response

    response = RedirectResponse("/courses", status_code=303)
    response.set_cookie(
        SESSION_COOKIE,
        session_id,
        httponly=True,
        samesite="lax",
        max_age=4 * 60 * 60,
        secure=False,  # TODO: Production 環境應設為 True
    )
    return response


@router.post("/login/icgu", response_class=HTMLResponse)
async def login_icgu(request: Request, csrf_protect: CsrfProtect = Depends()):
    from app.services.icgu_sync_service import sync_icgu_courses

    # 驗證 CSRF token
    await csrf_protect.validate_csrf(request)

    session_id, session_dir = create_session_dir()

    try:
        sync_result = await asyncio.to_thread(sync_icgu_courses, session_dir)
        display_name = sync_result.get("display_name") or "iCGU 使用者"
        save_session_meta(session_dir, display_name, sync_result)
        logger.info("login_success", username=display_name, method="icgu")
    except Exception as exc:
        destroy_session(session_id)
        logger.error("login_failed", method="icgu", error=str(exc))

        # 重新生成 CSRF token 給錯誤頁面
        csrf_token, signed_token = csrf_protect.generate_csrf_tokens()
        response = render_template(
            "login.html",
            {
                "request": request,
                "title": "登入",
                "error": f"iCGU 登入或同步失敗：{exc}",
                "logged_in": False,
                "csrf_token": csrf_token,
            },
        )
        csrf_protect.set_csrf_cookie(signed_token, response)
        return response

    response = RedirectResponse("/courses", status_code=303)
    response.set_cookie(
        SESSION_COOKIE,
        session_id,
        httponly=True,
        samesite="lax",
        max_age=4 * 60 * 60,
        secure=False,  # TODO: Production 環境應設為 True
    )
    return response


@router.post("/logout")
async def logout(request: Request, csrf_protect: CsrfProtect = Depends()):
    # 驗證 CSRF token
    await csrf_protect.validate_csrf(request)

    session_id = get_session_id(request)
    username = ""
    if session_id:
        from app.services.session_service import get_session_dir, load_session_meta
        session_dir = get_session_dir(request)
        if session_dir:
            meta = load_session_meta(session_dir)
            username = meta.get("username", "")

    destroy_session(session_id)
    logger.info("logout_success", username=username, session_id=session_id)

    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response
