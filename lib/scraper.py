from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

from lib.utils import ensure_parent, mask_identifier, normalize_key

MOOCS_LOGIN_URL = "https://moocs.cgu.edu.tw/learn/index.php"
MOOCS_COURSES_URL = "https://moocs.cgu.edu.tw/learn/mycourse/index.php"

TEXT_COURSE_RE = re.compile(
    r"^\s*(?:\d+\.\s*)?(?P<year>\d{3})-(?P<term>[123])-(?P<name>.+)-(?P<section>[A-Z]?\d+)(?:-.+)?\s*$"
)

SUBMIT_PAGE_JS = """
(targetPage) => {
  const form = document.querySelector('form#actFm') || Array.from(document.forms).find(f => f.page);
  if (!form || !form.page) return false;
  form.page.value = String(targetPage);
  form.submit();
  return true;
}
"""

USERNAME_SELECTORS = [
    'input[name="username"]',
    'input[name="user"]',
    'input[name="account"]',
    'input[name="login"]',
    'input[id*="user" i]',
    'input[id*="account" i]',
    'input[type="text"]',
    'input[type="email"]',
]
PASSWORD_SELECTORS = [
    'input[type="password"]',
    'input[name="password"]',
    'input[name="passwd"]',
    'input[name="pwd"]',
]
SUBMIT_SELECTORS = [
    'button[type="submit"]',
    'input[type="submit"]',
    'button:has-text("登入")',
    'input[value*="登入"]',
    'button:has-text("Login")',
    'input[value*="Login"]',
]


def parse_course_text(text: str) -> dict[str, str] | None:
    if "E-Learning" in text or "操作說明" in text:
        return None
    match = TEXT_COURSE_RE.match(text)
    if not match:
        return None
    return {
        "year": match.group("year"),
        "term": match.group("term"),
        "name": match.group("name"),
        "sectionid": match.group("section"),
    }


def read_csv_courses(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            return []
        rows = []
        for row in reader:
            fixed = {
                normalize_key(k): (v or "").strip()
                for k, v in row.items()
                if k is not None
            }
            section = (
                fixed.get("開課序號")
                or fixed.get("sectionid")
                or fixed.get("SECTIONID")
            )
            if not section:
                continue
            rows.append(
                {
                    "year": fixed.get("學年", ""),
                    "term": fixed.get("學期", ""),
                    "name": fixed.get("課程名稱", ""),
                    "sectionid": section,
                }
            )
        return rows


def read_text_courses(path: Path) -> list[dict[str, str]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        course = parse_course_text(line)
        if course:
            rows.append(course)
    return rows


def read_courses(path: Path) -> list[dict[str, str]]:
    if path.suffix.lower() == ".csv":
        rows = read_csv_courses(path)
        if rows:
            return rows
        raise ValueError(
            f"{path} 缺少開課序號欄位，無法準確查詢。請確保 CSV 有『開課序號』欄位。"
        )
    return read_text_courses(path)


def locate_first(page, selectors: list[str]):
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if locator.count() > 0:
                return locator
        except Exception:
            pass
    for frame in page.frames:
        for selector in selectors:
            locator = frame.locator(selector).first
            try:
                if locator.count() > 0:
                    return locator
            except Exception:
                pass
    return None


def extract_course_texts(page) -> list[str]:
    try:
        page.locator("table tr td:first-child").first.wait_for(
            state="attached", timeout=10000
        )
    except Exception:
        pass

    EXTRACT_COURSES_JS = """
    () => {
      const rows = [];
      const anchors = Array.from(document.querySelectorAll('table tr td:first-child a'));
      if (anchors.length > 0) {
        for (const a of anchors) {
          const t = (a.textContent || '').trim();
          if (!t) continue;
          if (/^課程名稱[:：]?$/i.test(t)) continue;
          rows.push(t);
        }
        return rows;
      }
      const tds = Array.from(document.querySelectorAll('table tr td:first-child'));
      for (const td of tds) {
        const t = (td.textContent || '').trim();
        if (!t) continue;
        if (/^課程名稱[:：]?$/i.test(t)) continue;
        if (/輸入課程名稱關鍵字|搜尋|報名說明/i.test(t)) continue;
        rows.push(t);
      }
      return rows;
    }
    """

    try:
        return page.evaluate(EXTRACT_COURSES_JS)
    except Exception as e:
        print(f"Extraction error: {e}")
        return []


def submit_course_page(page, target_page: int) -> bool:
    try:
        try:
            prev_texts = extract_course_texts(page)
        except Exception:
            prev_texts = []

        submitted = False
        try:
            if page.evaluate(SUBMIT_PAGE_JS, target_page):
                submitted = True
        except Exception:
            submitted = False

        if not submitted:
            for frame in page.frames:
                try:
                    if frame.evaluate(SUBMIT_PAGE_JS, target_page):
                        submitted = True
                        break
                except Exception:
                    pass

        if not submitted:
            return False

        waited = 0.0
        timeout = 10.0
        interval = 0.4
        while waited < timeout:
            try:
                page.wait_for_timeout(int(interval * 1000))
            except Exception:
                pass
            try:
                cur_texts = extract_course_texts(page)
                if cur_texts and cur_texts != prev_texts:
                    return True
            except Exception:
                pass
            waited += interval

        return True
    except Exception:
        return False


def scrape_moocs_courses(
    username: str,
    password: str,
    *,
    headless: bool,
    max_pages: int,
    save_path: Path | None,
    debug: bool = False,
) -> list[dict[str, str]]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "需要先安裝 Playwright：python3 -m pip install playwright && python3 -m playwright install chromium"
        ) from exc

    seen = set()
    courses = []
    raw_lines = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(ignore_https_errors=True)
        page = context.new_page()
        page.goto(MOOCS_LOGIN_URL, wait_until="domcontentloaded")

        username_input = locate_first(page, USERNAME_SELECTORS)
        password_input = locate_first(page, PASSWORD_SELECTORS)
        if username_input is None or password_input is None:
            browser.close()
            raise RuntimeError(
                "找不到 MOOCS 登入欄位；可改用 --headful 觀察頁面是否改版或有驗證碼。"
            )

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

        page.goto(MOOCS_COURSES_URL, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            page.wait_for_timeout(1500)

        try:
            locator = page.locator('a:has-text("全校課程")').first
            try:
                if locator.count() > 0:
                    locator.click()
                    try:
                        page.wait_for_load_state("domcontentloaded", timeout=8000)
                    except Exception:
                        page.wait_for_timeout(800)
            except Exception:
                pass
        except Exception:
            pass

        GET_TOTAL_PAGES_JS = """
        () => {
          if (typeof total_page === 'number' && total_page > 0) return total_page;
          const afterText = document.querySelector('.paginate-number-after');
          if (afterText) {
            const m = (afterText.textContent || '').match(/(\\d+)/);
            if (m) return parseInt(m[1], 10);
          }
          return null;
        }
        """

        detected_total = None
        try:
            detected = page.evaluate(GET_TOTAL_PAGES_JS)
            if isinstance(detected, (int, float)) and int(detected) > 0:
                detected_total = int(detected)
        except Exception:
            detected_total = None

        pages_to_scrape = (
            max_pages if max_pages and max_pages > 0 else (detected_total or 1)
        )
        if detected_total:
            pages_to_scrape = (
                min(max_pages, detected_total)
                if max_pages and max_pages > 0
                else detected_total
            )

        if not submit_course_page(page, 1):
            print("警告：無法跳回第 1 頁，從當前頁面開始抓取。", file=sys.stderr)
        else:
            try:
                page.wait_for_load_state("domcontentloaded", timeout=10000)
            except Exception:
                pass
            page.wait_for_timeout(700)

        for page_number in range(1, pages_to_scrape + 1):
            if page_number > 1:
                if not submit_course_page(page, page_number):
                    print(
                        f"警告：無法送出 MOOCS 第 {page_number} 頁分頁表單，停止翻頁。",
                        file=sys.stderr,
                    )
                    break
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=10000)
                except Exception:
                    pass
                page.wait_for_timeout(700)

            texts = extract_course_texts(page)
            if not texts and page_number > 1:
                print(
                    f"警告：MOOCS 第 {page_number} 頁未抓到文字，重試一次。",
                    file=sys.stderr,
                )
                page.wait_for_timeout(1000)
                texts = extract_course_texts(page)

            fresh = 0
            parsed = 0
            for text in texts:
                course = parse_course_text(text)
                if course is None:
                    if debug and text.strip():
                        print(f"DEBUG: 忽略非課程項目：{text.strip()}")
                    continue
                parsed += 1
                key = (course["year"], course["term"], course["sectionid"])
                if key in seen:
                    continue
                seen.add(key)
                fresh += 1
                courses.append(course)
                raw_lines.append(
                    f"{len(raw_lines) + 1}. {course['year']}-{course['term']}-{course['name']}-{course['sectionid']}"
                )

            print(f"MOOCS 第 {page_number} 頁：抓到 {parsed} 門，新增 {fresh} 門")
            if page_number > 1 and fresh == 0:
                print(
                    f"警告：第 {page_number} 頁沒有新增課程，可能已到最後一頁或分頁失敗。",
                    file=sys.stderr,
                )
                break

        browser.close()

    if not courses:
        raise RuntimeError(
            "沒有抓到任何 MOOCS 課程；請確認帳密正確，或用 --headful 檢查是否需要人工驗證。"
        )

    if save_path:
        ensure_parent(save_path)
        lines = [
            "# 長庚大學 MOOCS 課程清單",
            f"# 帳號：{mask_identifier(username)}",
            f"# 總計：{len(courses)} 門課程",
            "",
            *raw_lines,
        ]
        save_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"MOOCS 清單輸出：{save_path}")

    return courses


def scrape_stugrade_grades(
    username: str = "",
    password: str = "",
    *,
    headless: bool = False,
    timeout_ms: int = 300000,
) -> list[dict[str, str]]:
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

        url = "https://catalog.cgu.edu.tw/stugrade"
        print(f"正在前往 {url} ...")
        page.goto(url)

        # Check if redirected to Microsoft login
        is_redirected = False
        for _ in range(50):
            if "microsoftonline.com" in page.url:
                is_redirected = True
                break
            page.wait_for_timeout(100)

        if is_redirected:
            print("偵測到跳轉至 Microsoft 登入頁面，請在彈出的瀏覽器中完成登入與驗證。")
            elapsed = 0
            login_success = False
            while elapsed < timeout_ms:
                if "catalog.cgu.edu.tw/stugrade" in page.url and "microsoftonline.com" not in page.url:
                    page.wait_for_timeout(2000)
                    if "microsoftonline.com" not in page.url:
                        login_success = True
                        break
                page.wait_for_timeout(500)
                elapsed += 500

            if not login_success:
                browser.close()
                raise RuntimeError("等待微軟帳號登入逾時（5分鐘），同步終止。")

            print("登入成功，已返回目標頁面！")
        else:
            page.wait_for_timeout(2000)

        # Click #tabh0 to make sure the grades tab is selected
        try:
            tab_button = page.locator("#tabh0")
            tab_button.wait_for(state="visible", timeout=15000)
            tab_button.click()
            page.wait_for_timeout(1000)
        except Exception:
            pass

        EXTRACT_TABLE_JS = """
        () => {
          const tab = document.querySelector('#tab0');
          if (!tab) return null;
          const table = tab.querySelector('table');
          if (!table) return null;
          const rows = [];
          const trs = Array.from(table.querySelectorAll('tr'));
          for (const tr of trs) {
            const cells = Array.from(tr.querySelectorAll('td, th')).map(c => (c.textContent || '').trim());
            if (cells.length > 0) {
              rows.push(cells);
            }
          }
          return rows;
        }
        """

        table_rows = page.evaluate(EXTRACT_TABLE_JS)
        browser.close()

    if not table_rows:
        raise RuntimeError("無法在成績查詢分頁 (#tab0) 中找到學期成績表格。")

    # First row is the header: 學年 | 學期 | 科目代號 | 課程名稱 | 成績 | 實得學分 | 備註 | 登錄日
    header = table_rows[0]
    expected_headers = ["學年", "學期", "科目代號", "課程名稱", "成績", "實得學分"]
    
    # Map headers to indices
    header_indices = {}
    for h in expected_headers:
        try:
            header_indices[h] = header.index(h)
        except ValueError:
            pass

    year_idx = header_indices.get("學年", 0)
    term_idx = header_indices.get("學期", 1)
    call_id_idx = header_indices.get("科目代號", 2)
    name_idx = header_indices.get("課程名稱", 3)
    score_idx = header_indices.get("成績", 4)
    credits_idx = header_indices.get("實得學分", 5)

    courses = []
    for r in table_rows[1:]:
        if len(r) <= max(year_idx, term_idx, call_id_idx, name_idx, score_idx, credits_idx):
            continue
        
        if "無資料" in r[0] or (len(r) == 1 and "無資料" in r[0]):
            continue
            
        courses.append({
            "year": r[year_idx],
            "term": r[term_idx],
            "call_id": r[call_id_idx],
            "name": r[name_idx],
            "score": r[score_idx],
            "credits": r[credits_idx]
        })

    return courses

