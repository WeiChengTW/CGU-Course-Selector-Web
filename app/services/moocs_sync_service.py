from __future__ import annotations

import csv
from pathlib import Path

from lib.catalog import write_details
from lib.scraper import (
    MOOCS_LOGIN_URL,
    locate_first,
    PASSWORD_SELECTORS,
    SUBMIT_SELECTORS,
    USERNAME_SELECTORS,
    scrape_moocs_courses,
)


def parse_grade_rows(text: str) -> list[dict[str, str]]:
    rows = []
    seen = set()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    i = 0

    while i < len(lines):
        line = lines[i]
        if not line[:4].isdigit() or "-" not in line:
            i += 1
            continue

        term, name = line.split("-", 1)
        if i + 1 >= len(lines):
            break

        credits = lines[i + 1]
        score = ""
        next_index = i + 2
        if next_index < len(lines) and not (lines[next_index][:4].isdigit() and "-" in lines[next_index]):
            score = lines[next_index]
            next_index += 1

        key = (term, name)
        if key not in seen:
            seen.add(key)
            rows.append(
                {
                    "學年學期": term,
                    "課程名稱": name,
                    "學分數": credits,
                    "修課成績": score,
                }
            )
        i = next_index

    return rows


def _combined_body_text(page) -> str:
    texts = []
    for frame in [page, *page.frames]:
        try:
            body = frame.locator("body")
            if body.count() > 0:
                texts.append(body.inner_text())
        except Exception:
            pass
    return "\n".join(texts)


def _click_first_in_page_or_frame(page, selector: str) -> bool:
    for frame in [page, *page.frames]:
        try:
            locator = frame.locator(selector).first
            if locator.count() > 0:
                locator.click()
                return True
        except Exception:
            pass
    return False


def scrape_moocs_grade_rows(username: str, password: str, headless: bool = True) -> list[dict[str, str]]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "需要先安裝 Playwright：python -m pip install playwright && python -m playwright install chromium"
        ) from exc

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(ignore_https_errors=True)
        page = context.new_page()
        page.goto(MOOCS_LOGIN_URL, wait_until="domcontentloaded")

        username_input = locate_first(page, USERNAME_SELECTORS)
        password_input = locate_first(page, PASSWORD_SELECTORS)
        if username_input is None or password_input is None:
            browser.close()
            raise RuntimeError("找不到 MOOCS 登入欄位。")

        username_input.fill(username)
        password_input.fill(password)

        submit = locate_first(page, SUBMIT_SELECTORS)
        if submit is not None:
            submit.click()
        else:
            password_input.press("Enter")

        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            page.wait_for_timeout(1500)

        page.goto("https://moocs.cgu.edu.tw/learn/co_student_record.php", wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            page.wait_for_timeout(1500)

        rows = parse_grade_rows(_combined_body_text(page))

        browser.close()
        if not rows:
            raise RuntimeError("MOOCS 修課成績頁未解析到任何課程。")
        return rows


def _normalize_generated_csv(source_path: Path, target_path: Path) -> int:
    rows = []

    with source_path.open("r", encoding="utf-8-sig", newline="") as source_file:
        reader = csv.DictReader(source_file)
        for row in reader:
            rows.append(
                {
                    "學年學期": (row.get("學年學期") or "").replace("-", ""),
                    "課程名稱": row.get("課程名稱", ""),
                    "學分數": row.get("學分") or row.get("學分數", ""),
                    "修課成績": row.get("修課成績", ""),
                }
            )

    with target_path.open("w", encoding="utf-8-sig", newline="") as target_file:
        writer = csv.DictWriter(
            target_file,
            fieldnames=["學年學期", "課程名稱", "學分數", "修課成績"],
        )
        writer.writeheader()
        writer.writerows(rows)

    return len(rows)


def sync_moocs_courses(
    username,
    password,
    session_dir,
    headless=True,
    max_pages=30,
    delay=0.1,
) -> dict:
    raw_path = session_dir / "moocs_courses.txt"
    generated_path = session_dir / "courses_detail.csv"
    taken_path = session_dir / "taken_courses.csv"

    grade_rows = scrape_moocs_grade_rows(username, password, headless=headless)
    with taken_path.open("w", encoding="utf-8-sig", newline="") as target_file:
        writer = csv.DictWriter(
            target_file,
            fieldnames=["學年學期", "課程名稱", "學分數", "修課成績"],
        )
        writer.writeheader()
        writer.writerows(grade_rows)

    courses = scrape_moocs_courses(
        username,
        password,
        headless=headless,
        max_pages=max_pages,
        save_path=raw_path,
        debug=False,
    )
    catalog_count, total_credits, errors = write_details(courses, generated_path, delay)

    return {
        "count": len(grade_rows),
        "catalog_count": catalog_count,
        "total_credits": total_credits,
        "errors": errors,
        "taken_path": taken_path,
        "raw_path": raw_path,
    }
