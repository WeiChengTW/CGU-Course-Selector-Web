from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from secrets import token_urlsafe

from fastapi import Request
from fastapi.responses import RedirectResponse

from app.config import DATA_DIR


SESSION_COOKIE = "cgu_course_session"
SESSION_ROOT = DATA_DIR / "sessions"
RECORD_ROOT = DATA_DIR / "records"
SESSION_META_FILE = "session_meta.json"
COURSE_RECORD_FILES = ("taken_courses.csv", "courses_detail.csv", "moocs_courses.txt")
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")


def create_session_dir() -> tuple[str, Path]:
    session_id = token_urlsafe(32)
    session_dir = SESSION_ROOT / session_id
    session_dir.mkdir(parents=True, exist_ok=False)
    session_dir.chmod(0o700)
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


def _record_dir(username: str) -> Path:
    safe_username = re.sub(r"[^A-Za-z0-9_.-]", "_", username.strip())
    return RECORD_ROOT / safe_username


def has_saved_course_record(username: str) -> bool:
    record_dir = _record_dir(username)
    return (record_dir / "taken_courses.csv").exists()


def restore_course_record(username: str, session_dir: Path) -> dict | None:
    record_dir = _record_dir(username)
    meta = load_record_meta(username)
    if not (record_dir / "taken_courses.csv").exists():
        return None

    for fname in COURSE_RECORD_FILES:
        source = record_dir / fname
        if source.exists():
            shutil.copy2(source, session_dir / fname)

    return meta


def save_course_record(username: str, session_dir: Path, sync_result: dict | None = None) -> dict:
    record_dir = _record_dir(username)
    record_dir.mkdir(parents=True, exist_ok=True)
    record_dir.chmod(0o700)

    for fname in COURSE_RECORD_FILES:
        source = session_dir / fname
        if source.exists():
            shutil.copy2(source, record_dir / fname)

    meta = {
        "username": username,
        "last_synced_at": datetime.now().isoformat(),
    }
    if sync_result is not None:
        meta["last_sync_result"] = _safe_sync_result(sync_result)

    meta_path = record_dir / SESSION_META_FILE
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    meta_path.chmod(0o600)
    return meta


def load_record_meta(username: str) -> dict:
    meta_path = _record_dir(username) / SESSION_META_FILE
    if not meta_path.exists():
        return {}

    try:
        with meta_path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return {}


def _meta_path(session_dir: Path) -> Path:
    return session_dir / SESSION_META_FILE


def load_session_meta(session_dir: Path) -> dict:
    meta_path = _meta_path(session_dir)
    if not meta_path.exists():
        return {}

    try:
        with meta_path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return {}


def save_session_meta(
    session_dir: Path,
    username: str,
    sync_result: dict | None = None,
    last_synced_at: str | None = None,
) -> dict:
    now = datetime.now().isoformat()
    meta = {
        "username": username,
        "created_at": now,
        "last_synced_at": last_synced_at or now,
    }
    if sync_result is not None:
        meta["last_sync_result"] = _safe_sync_result(sync_result)

    meta_path = _meta_path(session_dir)
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    meta_path.chmod(0o600)
    return meta


def update_session_sync_meta(session_dir: Path, sync_result: dict | None = None) -> dict:
    meta = load_session_meta(session_dir)
    meta["last_synced_at"] = datetime.now().isoformat()
    if sync_result is not None:
        meta["last_sync_result"] = _safe_sync_result(sync_result)

    meta_path = _meta_path(session_dir)
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    meta_path.chmod(0o600)
    return meta


def _safe_sync_result(sync_result: dict) -> dict:
    return {
        key: str(value) if isinstance(value, Path) else value
        for key, value in sync_result.items()
    }


def is_logged_in(request: Request) -> bool:
    return get_session_dir(request) is not None
