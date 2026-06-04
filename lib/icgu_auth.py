from __future__ import annotations
from pathlib import Path
import sys

from lib.icgu_scraper import extract_course_rows, extract_exemption_rows

ICGU_ENTRY_URL = "https://catalog.cgu.edu.tw/stugrade"
LOGIN_TIMEOUT_MS = 180_000


def _wait_for_stugrade_content(page) -> None:
    is_redirected = False
    for _ in range(50):
        if "microsoftonline.com" in page.url:
            is_redirected = True
            break
        page.wait_for_timeout(100)

    if is_redirected:
        print("偵測到跳轉至微軟登入頁面，等待使用者登入...", file=sys.stderr)
        elapsed = 0
        while elapsed < LOGIN_TIMEOUT_MS:
            if "catalog.cgu.edu.tw/stugrade" in page.url and "microsoftonline.com" not in page.url:
                page.wait_for_timeout(2000)
                if "microsoftonline.com" not in page.url:
                    break
            page.wait_for_timeout(500)
            elapsed += 500
        else:
            raise RuntimeError("登入逾時（3分鐘），請重試。")

    page.wait_for_function(
        """
        () => {
            const text = document.body?.innerText || '';
            if (window.location.href.includes('microsoftonline.com')) return false;
            return text.includes('課程') && text.includes('學分') && text.includes('成績');
        }
        """,
        timeout=30000,
    )


def scrape_icgu_records_interactively(session_dir: Path, headless: bool = False) -> dict:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "需要先安裝 Playwright：python -m pip install playwright && python -m playwright install chromium"
        ) from exc

    storage_path = session_dir / "stugrade_storage.json"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)

        if storage_path.exists():
            context = browser.new_context(storage_state=str(storage_path), ignore_https_errors=True)
        else:
            context = browser.new_context(ignore_https_errors=True)

        page = context.new_page()
        errors = []

        try:
            page.goto(ICGU_ENTRY_URL, wait_until="domcontentloaded")

            is_redirected = False
            for _ in range(30):
                if "microsoftonline.com" in page.url:
                    is_redirected = True
                    break
                page.wait_for_timeout(100)

            if is_redirected:
                if headless:
                    browser.close()
                    raise ConnectionAbortedError("需要進行 Microsoft 互動式登入")
                _wait_for_stugrade_content(page)
            else:
                try:
                    _wait_for_stugrade_content(page)
                except Exception:
                    if headless:
                        browser.close()
                        raise ConnectionAbortedError("需要進行 Microsoft 互動式登入")
                    _wait_for_stugrade_content(page)

            courses = extract_course_rows(page)
            exemptions, scrape_errors = extract_exemption_rows(page)
            if scrape_errors:
                errors.extend(scrape_errors)

            moocs_grade_rows = []
            moocs_display_name = ""
            try:
                print("正在透過單一登入 (SSO) 自動登入 MOOCS 以獲取修課成績...", file=sys.stderr)
                page.goto("https://moocs.cgu.edu.tw/sso/cgu_o365login.php", wait_until="domcontentloaded")
                page.wait_for_timeout(2000)

                page.goto("https://moocs.cgu.edu.tw/learn/co_student_record.php", wait_until="domcontentloaded")
                try:
                    page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    page.wait_for_timeout(1500)

                from lib.icgu_scraper import combined_body_text, parse_grade_rows
                moocs_grade_rows = parse_grade_rows(combined_body_text(page))

                try:
                    name_el = page.locator(".user .name").first
                    if name_el.count() > 0:
                        moocs_display_name = name_el.inner_text().strip()
                except Exception:
                    pass

                print(f"成功自 MOOCS 抓取到 {len(moocs_grade_rows)} 筆成績。", file=sys.stderr)
            except Exception as moocs_ex:
                print(f"MOOCS SSO 登入或成績抓取失敗（已忽略）：{moocs_ex}", file=sys.stderr)
                errors.append(f"MOOCS 整合同步失敗: {moocs_ex}")

            # Merge MOOCS grades into stugrade courses (stugrade takes priority)
            completed_keys = set()
            for c in courses:
                sem = c.get("學年學期", "")
                year = sem[:3] if len(sem) >= 3 else ""
                term = sem[3:] if len(sem) >= 4 else ""
                name = c.get("課程名稱", "")
                completed_keys.add((year, term, name))

            for mr in moocs_grade_rows:
                sem = mr.get("學年學期", "")
                year = sem[:3] if len(sem) >= 3 else ""
                term = sem[3:] if len(sem) >= 4 else ""
                name = mr.get("課程名稱", "")
                key = (year, term, name)
                if key not in completed_keys:
                    courses.append({
                        "學年學期": mr["學年學期"],
                        "課程名稱": name,
                        "學分數": mr.get("學分數", ""),
                        "修課成績": mr.get("修課成績", ""),
                        "call_id": "",
                    })
                    completed_keys.add(key)

            # Scrape course booking (預選課程)
            booking_courses = []
            try:
                print("正在查詢預選課程...", file=sys.stderr)
                page.goto("https://catalog.cgu.edu.tw/booking", wait_until="domcontentloaded")
                page.wait_for_timeout(2000)
                from lib.icgu_scraper import extract_booking_rows
                booking_courses = extract_booking_rows(page)
                print(f"找到 {len(booking_courses)} 門預選課程。", file=sys.stderr)
            except Exception as be:
                print(f"預選課程查詢失敗（已忽略）：{be}", file=sys.stderr)
                errors.append(f"預選課程查詢失敗: {be}")

            # Scrape Microsoft account profile
            import re as _re
            profile: dict = {}
            try:
                print("正在取得 Microsoft 帳號資料...", file=sys.stderr)
                page.goto("https://myaccount.microsoft.com/", wait_until="domcontentloaded")
                page.wait_for_timeout(3000)

                name_el = page.locator(".fui-Subtitle2").first
                if name_el.count() > 0:
                    profile["display_name"] = name_el.inner_text().strip()

                dept_el = page.locator("span[title*='學生-']").first
                if dept_el.count() > 0:
                    dept_raw = dept_el.get_attribute("title") or ""
                    profile["department_raw"] = dept_raw
                    m = _re.search(r'[一-鿿]+系', dept_raw)
                    if m:
                        profile["department"] = m.group(0)

                email_el = page.locator("span[title*='@cgu.edu.tw']").first
                if email_el.count() > 0:
                    profile["email"] = email_el.get_attribute("title") or ""

                print(f"帳號資料：{profile}", file=sys.stderr)
            except Exception as pe:
                print(f"取得 Microsoft 帳號資料失敗（已忽略）：{pe}", file=sys.stderr)

            if moocs_display_name and not profile.get("display_name"):
                profile["display_name"] = moocs_display_name

            context.storage_state(path=str(storage_path))

            return {
                "courses": courses,
                "exemptions": exemptions,
                "booking_courses": booking_courses,
                "profile": profile,
                "errors": errors,
            }
        finally:
            context.close()
            browser.close()


def run_icgu_sync_subprocess(session_dir: Path, headless: bool) -> dict:
    import subprocess
    import json

    cmd = [
        sys.executable,
        "-m",
        "lib.icgu_auth",
        str(session_dir),
        "true" if headless else "false"
    ]

    cwd = Path(__file__).resolve().parent.parent

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(cwd)
    )

    if result.stderr:
        print(result.stderr, file=sys.stderr, end="")

    if result.returncode == 2:
        raise ConnectionAbortedError("需要進行 Microsoft 互動式登入")
    elif result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout or f"子程序結束代碼非零: {result.returncode}")

    json_str = None
    for line in result.stdout.splitlines():
        trimmed = line.strip()
        if trimmed.startswith("{") and trimmed.endswith("}"):
            json_str = trimmed
            break

    if not json_str:
        lines = [l.strip() for l in result.stdout.splitlines() if l.strip()]
        if lines:
            json_str = lines[-1]

    try:
        return json.loads(json_str or result.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"無法解析子程序輸出: {result.stdout}") from e


if __name__ == "__main__":
    import json
    if len(sys.argv) < 3:
        print("Usage: python -m lib.icgu_auth <session_dir> <headless_bool>", file=sys.stderr)
        sys.exit(1)

    sess_dir = Path(sys.argv[1])
    hl = sys.argv[2].lower() == "true"

    try:
        res = scrape_icgu_records_interactively(sess_dir, headless=hl)
        print(json.dumps(res, ensure_ascii=False))
    except ConnectionAbortedError:
        sys.exit(2)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
