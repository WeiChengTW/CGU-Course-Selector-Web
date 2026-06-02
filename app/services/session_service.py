from __future__ import annotations

import re
import shutil
from pathlib import Path
from secrets import token_urlsafe

from fastapi import Request
from fastapi.responses import RedirectResponse

from app.config import DATA_DIR


SESSION_COOKIE = "cgu_course_session"
SESSION_ROOT = DATA_DIR / "sessions"
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")


def create_session_dir() -> tuple[str, Path]:
    session_id = token_urlsafe(32)
    session_dir = SESSION_ROOT / session_id
    session_dir.mkdir(parents=True, exist_ok=False)
    return session_id, session_dir


def is_valid_session_id(session_id: str | None) -> bool:
    return bool(session_id and SESSION_ID_RE.fullmatch(session_id))


def get_session_id(request: Request) -> str | None:
    session_id = request.cookies.get(SESSION_COOKIE)
    if not is_valid_session_id(session_id):
        return None
    return session_id


def get_session_dir(request: Request) -> Path | None:
    session_id = get_session_id(request)
    if session_id is None:
        return None

    session_dir = SESSION_ROOT / session_id
    if not session_dir.is_dir():
        return None
    return session_dir


def require_session_dir(request: Request) -> Path | RedirectResponse:
    session_dir = get_session_dir(request)
    if session_dir is None:
        return RedirectResponse("/login", status_code=303)
    return session_dir


def destroy_session(session_id: str | None) -> None:
    if not is_valid_session_id(session_id):
        return

    session_dir = SESSION_ROOT / session_id
    if session_dir.exists():
        shutil.rmtree(session_dir)


def is_logged_in(request: Request) -> bool:
    return get_session_dir(request) is not None
