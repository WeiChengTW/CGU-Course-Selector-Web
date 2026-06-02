# MOOCS Session Login Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add MOOCS/校務系統帳密登入 so each browser session syncs and reads its own student course data without storing passwords.

**Architecture:** Add a small auth layer with HttpOnly cookie sessions, per-session data directories, and a MOOCS sync service that wraps the existing Graduation-Credit-Calculator scraper/catalog writer. Route handlers stop using global `CourseService(DATA_DIR)` and instead construct services from the current session directory.

**Tech Stack:** FastAPI, Jinja2 templates, Playwright-backed existing MOOCS scraper, Python stdlib `secrets`/`shutil`, Tailwind CDN, Alpine.js.

---

## File structure

- Create `app/services/session_service.py` — owns session id generation, cookie name, session directory resolution, login requirement, cleanup.
- Create `app/services/moocs_sync_service.py` — owns calling `scrape_moocs_courses()` and `write_details()`, then normalizing output into the `taken_courses.csv` shape expected by the web app.
- Create `app/routes/auth.py` — login/logout route handlers.
- Create `app/templates/login.html` — login form and loading state.
- Modify `app/main.py` — include auth router.
- Modify `app/templates/base.html` — show login/logout controls.
- Modify `app/routes/courses.py` — require session and read session-local courses.
- Modify `app/routes/catalog.py` — require session for page/data and use session-local course status.
- Modify `app/routes/graduation.py` — require session and read session-local report if present.
- Modify `app/routes/recommend.py` — pass session/login state to template.
- Modify `app/services/course_service.py` — support both existing demo CSV shape and MOOCS generated CSV shape.
- Modify `app/services/graduation_service.py` — no API changes required unless current constructor assumes global data only; instantiate per session in routes.

---

## Task 1: Add session service

**Files:**
- Create: `app/services/session_service.py`

- [ ] **Step 1: Create session service**

Create `app/services/session_service.py`:

```python
from __future__ import annotations

import shutil
from pathlib import Path
from secrets import token_urlsafe

from fastapi import Request
from fastapi.responses import RedirectResponse

from app.config import DATA_DIR

SESSION_COOKIE = "cgu_course_session"
SESSION_ROOT = DATA_DIR / "sessions"


def create_session_dir() -> tuple[str, Path]:
    session_id = token_urlsafe(32)
    session_dir = SESSION_ROOT / session_id
    session_dir.mkdir(parents=True, exist_ok=False)
    return session_id, session_dir


def get_session_id(request: Request) -> str | None:
    session_id = request.cookies.get(SESSION_COOKIE)
    if not session_id:
        return None
    if "/" in session_id or "\\" in session_id or ".." in session_id:
        return None
    return session_id


def get_session_dir(request: Request) -> Path | None:
    session_id = get_session_id(request)
    if not session_id:
        return None
    session_dir = SESSION_ROOT / session_id
    if not session_dir.exists():
        return None
    return session_dir


def require_session_dir(request: Request) -> Path | RedirectResponse:
    session_dir = get_session_dir(request)
    if session_dir is None:
        return RedirectResponse(url="/login", status_code=303)
    return session_dir


def destroy_session(session_id: str | None) -> None:
    if not session_id:
        return
    if "/" in session_id or "\\" in session_id or ".." in session_id:
        return
    session_dir = SESSION_ROOT / session_id
    if session_dir.exists():
        shutil.rmtree(session_dir)


def is_logged_in(request: Request) -> bool:
    return get_session_dir(request) is not None
```

- [ ] **Step 2: Syntax check**

Run:

```powershell
python -m py_compile app/services/session_service.py
```

Expected: command exits with code 0 and prints no errors.

---

## Task 2: Add MOOCS sync service

**Files:**
- Create: `app/services/moocs_sync_service.py`
- Read dependency: `../Graduation-Credit-Calculator/lib/scraper.py`
- Read dependency: `../Graduation-Credit-Calculator/lib/catalog.py`

- [ ] **Step 1: Create sync service that calls existing scraper**

Create `app/services/moocs_sync_service.py`:

```python
from __future__ import annotations

import csv
import sys
from pathlib import Path

from app.config import CREDIT_CALC_DIR

if str(CREDIT_CALC_DIR) not in sys.path:
    sys.path.insert(0, str(CREDIT_CALC_DIR))

from lib.catalog import write_details  # noqa: E402
from lib.scraper import scrape_moocs_courses  # noqa: E402


def _normalize_generated_csv(source_path: Path, target_path: Path) -> int:
    with source_path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    target_path.parent.mkdir(parents=True, exist_ok=True)
    with target_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["學年學期", "課程名稱", "學分數", "修課成績"])
        writer.writeheader()
        for row in rows:
            semester = (row.get("學年學期") or "").replace("-", "")
            writer.writerow(
                {
                    "學年學期": semester,
                    "課程名稱": row.get("課程名稱", ""),
                    "學分數": row.get("學分") or row.get("學分數", ""),
                    "修課成績": row.get("修課成績", ""),
                }
            )
    return len(rows)


def sync_moocs_courses(
    *,
    username: str,
    password: str,
    session_dir: Path,
    headless: bool = True,
    max_pages: int = 30,
    delay: float = 0.1,
) -> dict:
    raw_path = session_dir / "moocs_courses.txt"
    generated_path = session_dir / "courses_detail.csv"
    taken_path = session_dir / "taken_courses.csv"

    courses = scrape_moocs_courses(
        username,
        password,
        headless=headless,
        max_pages=max_pages,
        save_path=raw_path,
        debug=False,
    )
    count, total_credits, errors = write_details(courses, generated_path, delay)
    normalized_count = _normalize_generated_csv(generated_path, taken_path)

    return {
        "count": normalized_count,
        "catalog_count": count,
        "total_credits": total_credits,
        "errors": errors,
        "taken_path": str(taken_path),
        "raw_path": str(raw_path),
    }
```

- [ ] **Step 2: Syntax check**

Run:

```powershell
python -m py_compile app/services/moocs_sync_service.py
```

Expected: command exits with code 0 and prints no errors.

---

## Task 3: Make CourseService accept both CSV shapes

**Files:**
- Modify: `app/services/course_service.py`

- [ ] **Step 1: Add helper methods to CourseService**

In `CourseService`, add these methods after `get_courses()`:

```python
    def _get_name(self, course: dict) -> str:
        return (course.get("課程名稱") or course.get("CCOURSENAME") or "").strip()

    def _get_credits(self, course: dict) -> str:
        return (course.get("學分數") or course.get("學分") or course.get("CREDITS") or "").strip()

    def _get_score(self, course: dict) -> str:
        return (course.get("修課成績") or "").strip()
```

- [ ] **Step 2: Replace direct field access in service methods**

Update existing methods so they use the helpers:

```python
    def get_passed_course_names(self) -> set[str]:
        if self._passed_names_cache is not None:
            return self._passed_names_cache

        courses = self.get_courses()
        self._passed_names_cache = set()

        for c in courses:
            name = self._get_name(c)
            score = self._get_score(c)

            if name and self._is_passed(score):
                self._passed_names_cache.add(name)

        return self._passed_names_cache

    def get_all_course_names(self) -> set[str]:
        courses = self.get_courses()
        return {self._get_name(c) for c in courses if self._get_name(c)}

    def check_course_status(self, course_name: str) -> dict:
        courses = self.get_courses()
        course_name = course_name.strip()

        for c in courses:
            taken_name = self._get_name(c)

            if course_name == taken_name or course_name in taken_name or taken_name in course_name:
                score = self._get_score(c)
                credits = self._get_credits(c)

                if not score:
                    return {"status": "in_progress", "score": None, "credits": credits}

                if self._is_passed(score):
                    return {"status": "passed", "score": score, "credits": credits}
                return {"status": "failed", "score": score, "credits": credits}

        return {"status": "not_taken", "score": None, "credits": None}
```

In `get_taken_courses_info()`, replace:

```python
score = c.get("修課成績", "")
total_passed_credits += float(c.get("學分數", 0))
```

with:

```python
score = self._get_score(c)
total_passed_credits += float(self._get_credits(c) or 0)
```

- [ ] **Step 3: Syntax check**

Run:

```powershell
python -m py_compile app/services/course_service.py
```

Expected: command exits with code 0 and prints no errors.

---

## Task 4: Add auth routes and login template

**Files:**
- Create: `app/routes/auth.py`
- Create: `app/templates/login.html`
- Modify: `app/main.py`

- [ ] **Step 1: Create auth route module**

Create `app/routes/auth.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.services.moocs_sync_service import sync_moocs_courses
from app.services.session_service import (
    SESSION_COOKIE,
    create_session_dir,
    destroy_session,
    get_session_id,
    is_logged_in,
)
from app.templates_config import render_template

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str = ""):
    if is_logged_in(request):
        return RedirectResponse(url="/courses", status_code=303)
    return render_template(
        "login.html",
        {"request": request, "title": "登入", "error": error, "logged_in": False},
    )


@router.post("/login")
async def login(username: str = Form(...), password: str = Form(...)):
    session_id, session_dir = create_session_dir()
    try:
        sync_moocs_courses(username=username.strip(), password=password, session_dir=session_dir)
    except Exception:
        destroy_session(session_id)
        return render_template(
            "login.html",
            {
                "request": None,
                "title": "登入",
                "error": "登入或同步失敗，請確認帳密正確，或 MOOCS 是否需要驗證碼。",
                "logged_in": False,
            },
        )

    response = RedirectResponse(url="/courses", status_code=303)
    response.set_cookie(
        SESSION_COOKIE,
        session_id,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 4,
    )
    return response


@router.post("/logout")
async def logout(request: Request):
    session_id = get_session_id(request)
    destroy_session(session_id)
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response
```

- [ ] **Step 2: Create login template**

Create `app/templates/login.html`:

```html
{% extends "base.html" %}

{% block title %}登入 - 長庚大學選課系統{% endblock %}

{% block content %}
<div class="max-w-md mx-auto bg-white rounded-xl shadow-lg border border-gray-200 overflow-hidden" x-data="{ loading: false }">
    <div class="bg-gradient-to-r from-[#E39800] to-[#C48400] text-white px-6 py-5">
        <h1 class="text-2xl font-bold">MOOCS 登入</h1>
        <p class="text-[#F5B333] text-sm mt-1">登入後會即時同步你的已修課程</p>
    </div>

    <form method="post" action="/login" class="p-6 space-y-4" @submit="loading = true">
        {% if error %}
        <div class="bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 text-sm">
            {{ error }}
        </div>
        {% endif %}

        <div>
            <label class="block text-sm text-gray-600 mb-1">MOOCS 帳號</label>
            <input name="username" type="text" required autocomplete="username"
                   class="w-full border border-gray-300 rounded-lg px-3 py-2 text-gray-700 focus:ring-2 focus:ring-[#E39800] focus:border-transparent">
        </div>

        <div>
            <label class="block text-sm text-gray-600 mb-1">MOOCS 密碼</label>
            <input name="password" type="password" required autocomplete="current-password"
                   class="w-full border border-gray-300 rounded-lg px-3 py-2 text-gray-700 focus:ring-2 focus:ring-[#E39800] focus:border-transparent">
        </div>

        <button type="submit"
                :disabled="loading"
                class="w-full bg-gradient-to-r from-[#E39800] to-[#C48400] text-white rounded-lg px-4 py-2.5 font-medium hover:from-[#C48400] hover:to-[#333333] disabled:from-gray-400 disabled:to-gray-400 transition-all">
            <span x-show="!loading">登入並同步課程</span>
            <span x-show="loading">正在登入 MOOCS 並同步課程，第一次需要等待...</span>
        </button>

        <p class="text-xs text-gray-500 leading-relaxed">
            系統不會保存你的密碼。同步完成後只保留本次 session 的課程資料，登出後會清除暫存資料。
        </p>
    </form>
</div>
{% endblock %}
```

- [ ] **Step 3: Register auth router**

In `app/main.py`, change:

```python
from app.routes import courses, catalog, graduation, recommend, home
```

to:

```python
from app.routes import courses, catalog, graduation, recommend, home, auth
```

Then add after `app.include_router(home.router)`:

```python
app.include_router(auth.router, tags=["auth"])
```

- [ ] **Step 4: Syntax check**

Run:

```powershell
python -m py_compile app/routes/auth.py app/main.py
```

Expected: command exits with code 0 and prints no errors.

---

## Task 5: Update base navigation login state

**Files:**
- Modify: `app/templates/base.html`
- Modify route contexts in later tasks to pass `logged_in`

- [ ] **Step 1: Replace nav right side with login/logout controls**

In `app/templates/base.html`, replace the `<div class="flex space-x-1">...</div>` navigation block with:

```html
<div class="flex items-center space-x-1">
    <a href="/courses"
       class="px-4 py-2 rounded-lg hover:bg-[#C48400] transition {% if title == '已修課程' %}bg-[#C48400]{% endif %}">
        已修課程
    </a>
    <a href="/catalog"
       class="px-4 py-2 rounded-lg hover:bg-[#C48400] transition {% if title == '課程預選' or title == '開課查詢' %}bg-[#C48400]{% endif %}">
        開課查詢
    </a>
    <a href="/graduation"
       class="px-4 py-2 rounded-lg hover:bg-[#C48400] transition {% if title == '畢業進度' %}bg-[#C48400]{% endif %}">
        畢業進度
    </a>
    <a href="/recommend"
       class="px-4 py-2 rounded-lg hover:bg-[#C48400] transition {% if title == '選課建議' %}bg-[#C48400]{% endif %}">
        選課建議
    </a>
    {% if logged_in %}
    <form method="post" action="/logout" class="ml-2">
        <button type="submit" class="px-4 py-2 rounded-lg bg-white/15 hover:bg-[#C48400] transition">
            登出
        </button>
    </form>
    {% else %}
    <a href="/login" class="ml-2 px-4 py-2 rounded-lg bg-white/15 hover:bg-[#C48400] transition {% if title == '登入' %}bg-[#C48400]{% endif %}">
        登入
    </a>
    {% endif %}
</div>
```

- [ ] **Step 2: Open login page manually after server is running**

Run after implementation tasks are complete:

```powershell
python -m uvicorn app.main:app --reload
```

Expected: server starts. Visit `http://127.0.0.1:8000/login`; nav shows 登入 and no 登出.

---

## Task 6: Protect courses routes and use session-local CSV

**Files:**
- Modify: `app/routes/courses.py`

- [ ] **Step 1: Replace global service usage**

Update imports in `app/routes/courses.py` to:

```python
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.services.course_service import CourseService
from app.services.session_service import get_session_dir, is_logged_in
from app.templates_config import render_template
```

Remove:

```python
from app.config import DATA_DIR
course_service = CourseService(DATA_DIR)
```

- [ ] **Step 2: Update page route**

Replace `courses_page()` with:

```python
@router.get("/", response_class=HTMLResponse)
async def courses_page(request: Request):
    if not is_logged_in(request):
        return RedirectResponse(url="/login", status_code=303)
    return render_template(
        "courses.html",
        {"request": request, "title": "已修課程", "logged_in": True},
    )
```

- [ ] **Step 3: Update data route**

Replace `get_courses_data()` with:

```python
@router.get("/data", response_class=JSONResponse)
async def get_courses_data(request: Request):
    session_dir = get_session_dir(request)
    if session_dir is None:
        return JSONResponse({"error": "請先登入"}, status_code=401)
    return CourseService(session_dir).get_courses()
```

- [ ] **Step 4: Syntax check**

Run:

```powershell
python -m py_compile app/routes/courses.py
```

Expected: command exits with code 0 and prints no errors.

---

## Task 7: Protect catalog routes and use session-local status

**Files:**
- Modify: `app/routes/catalog.py`

- [ ] **Step 1: Update imports and remove global course service**

Change imports to include session helpers:

```python
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from app.services.session_service import get_session_dir, is_logged_in
```

Remove:

```python
from app.config import DATA_DIR
course_service = CourseService(DATA_DIR)
```

- [ ] **Step 2: Protect catalog page**

Replace `catalog_page()` with:

```python
@router.get("/", response_class=HTMLResponse)
async def catalog_page(request: Request):
    if not is_logged_in(request):
        return RedirectResponse(url="/login", status_code=303)
    return render_template(
        "catalog.html",
        {"request": request, "title": "課程預選", "logged_in": True},
    )
```

- [ ] **Step 3: Use session CourseService in search**

Add `request: Request` as the first parameter of `search_courses()`:

```python
async def search_courses(
    request: Request,
    year: int = Query(..., description="學年"),
```

At the start of the function body, add:

```python
    session_dir = get_session_dir(request)
    if session_dir is None:
        return JSONResponse({"error": "請先登入"}, status_code=401)
    course_service = CourseService(session_dir)
```

Keep the existing `CatalogService.search_courses(...)` call. The loop that marks `course_status` should use this local `course_service`.

- [ ] **Step 4: Update taken courses endpoint**

Replace `get_taken_courses()` with:

```python
@router.get("/taken-courses", response_class=JSONResponse)
async def get_taken_courses(request: Request):
    session_dir = get_session_dir(request)
    if session_dir is None:
        return JSONResponse({"error": "請先登入"}, status_code=401)
    return CourseService(session_dir).get_taken_courses_info()
```

- [ ] **Step 5: Syntax check**

Run:

```powershell
python -m py_compile app/routes/catalog.py
```

Expected: command exits with code 0 and prints no errors.

---

## Task 8: Protect graduation and recommend pages

**Files:**
- Modify: `app/routes/graduation.py`
- Modify: `app/routes/recommend.py`

- [ ] **Step 1: Update graduation imports**

In `app/routes/graduation.py`, use:

```python
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from app.services.session_service import get_session_dir, is_logged_in
```

Remove global `graduation_service = GraduationService(DATA_DIR)` and the unused `DATA_DIR` import.

- [ ] **Step 2: Protect graduation page**

Replace `graduation_page()` with:

```python
@router.get("/", response_class=HTMLResponse)
async def graduation_page(request: Request):
    if not is_logged_in(request):
        return RedirectResponse(url="/login", status_code=303)
    return render_template(
        "graduation.html",
        {"request": request, "title": "畢業進度", "logged_in": True},
    )
```

- [ ] **Step 3: Use session-local graduation service**

Replace `get_graduation_data()` with:

```python
@router.get("/data", response_class=JSONResponse)
async def get_graduation_data(request: Request):
    session_dir = get_session_dir(request)
    if session_dir is None:
        return JSONResponse({"error": "請先登入"}, status_code=401)

    report = GraduationService(session_dir).get_report()
    if report is None:
        return {
            "status": "尚未分析",
            "recognized_credits": 0,
            "required_credits": 128,
            "missing_credits": 128,
            "one_sentence_summary": "請先執行畢業規則分析",
            "requirements": [],
            "missing_items": [],
            "manual_review_items": [],
            "next_semester_recommendations": [],
        }
    return report
```

- [ ] **Step 4: Protect recommend page**

In `app/routes/recommend.py`, import `RedirectResponse` and `is_logged_in`, then update the page route to redirect logged-out users and pass `logged_in: True` to `render_template`.

The final route should look like:

```python
@router.get("/", response_class=HTMLResponse)
async def recommend_page(request: Request):
    if not is_logged_in(request):
        return RedirectResponse(url="/login", status_code=303)
    return render_template(
        "recommend.html",
        {"request": request, "title": "選課建議", "logged_in": True},
    )
```

- [ ] **Step 5: Syntax check**

Run:

```powershell
python -m py_compile app/routes/graduation.py app/routes/recommend.py
```

Expected: command exits with code 0 and prints no errors.

---

## Task 9: Pass logged_in state on public home page

**Files:**
- Modify: `app/routes/home.py`

- [ ] **Step 1: Import login state helper**

Add:

```python
from app.services.session_service import is_logged_in
```

- [ ] **Step 2: Pass logged_in to template context**

Update the home route render context so it includes:

```python
{"request": request, "title": "首頁", "logged_in": is_logged_in(request)}
```

- [ ] **Step 3: Syntax check**

Run:

```powershell
python -m py_compile app/routes/home.py
```

Expected: command exits with code 0 and prints no errors.

---

## Task 10: Full manual verification

**Files:**
- No code changes unless verification finds a bug.

- [ ] **Step 1: Start server**

Run:

```powershell
python -m uvicorn app.main:app --reload
```

Expected: server starts at `http://127.0.0.1:8000`.

- [ ] **Step 2: Verify logged-out redirect**

Open:

```text
http://127.0.0.1:8000/courses
```

Expected: redirected to `/login`.

- [ ] **Step 3: Verify failed login message**

Submit an intentionally wrong MOOCS username/password.

Expected: login page remains visible and shows:

```text
登入或同步失敗，請確認帳密正確，或 MOOCS 是否需要驗證碼。
```

- [ ] **Step 4: Verify successful login with valid credentials**

Submit a valid MOOCS username/password.

Expected:

- Browser redirects to `/courses`.
- `data/sessions/<session_id>/taken_courses.csv` exists.
- Courses page shows rows from that CSV.
- No password appears in any generated file.

- [ ] **Step 5: Verify catalog uses current session data**

Open:

```text
http://127.0.0.1:8000/catalog
```

Search for a course already in the synced MOOCS data.

Expected: course result is marked `修習中` if no grade exists in MOOCS output, or `已通過` if the session CSV contains a passing score.

- [ ] **Step 6: Verify logout cleanup**

Click 登出.

Expected:

- Redirected to `/login`.
- Session cookie is removed.
- The corresponding `data/sessions/<session_id>` directory is deleted.
- Visiting `/courses` again redirects to `/login`.

---

## Self-review notes

- Spec coverage: login routes, session directories, password non-persistence, route data isolation, logout cleanup, and verification are covered.
- Scope: this plan does not add a database or long-term account system, matching the spec non-goals.
- Known limitation: MOOCS output may not include final grades, so synced courses may show as `修習中` unless the source data later includes `修課成績`. This matches the current available scraper output and avoids inventing unavailable grade data.
