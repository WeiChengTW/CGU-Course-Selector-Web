from __future__ import annotations

from typing import Iterable

COURSE_FIELDS = ["學年學期", "課程名稱", "學分數", "修課成績"]
EXEMPTION_FIELDS = ["學年學期", "課程名稱", "學分數", "抵免類型", "核准狀態", "原始備註"]


def _clean(value: object) -> str:
    return str(value or "").strip()


def _term(value: object) -> str:
    return _clean(value).replace("-", "")


def _first(row: dict[str, str], *keys: str) -> str:
    for key in keys:
        value = _clean(row.get(key))
        if value:
            return value
    return ""


def parse_table_rows(raw_rows: list[list[str]]) -> list[dict[str, str]]:
    if len(raw_rows) < 2:
        return []

    headers = [_clean(cell) for cell in raw_rows[0]]
    rows: list[dict[str, str]] = []
    for raw_row in raw_rows[1:]:
        if not any(_clean(cell) for cell in raw_row):
            continue
        row: dict[str, str] = {}
        for index, cell in enumerate(raw_row):
            header = headers[index] if index < len(headers) and headers[index] else str(index)
            row[header] = _clean(cell)
        rows.append(row)
    return rows


def normalize_course_row(row: dict[str, str]) -> dict[str, str]:
    year = _clean(row.get("學年"))
    term = _clean(row.get("學期"))
    if year and term:
        sem = year + term
    else:
        sem = _term(_first(row, "學年學期", "學期", "0"))

    return {
        "學年學期": sem,
        "課程名稱": _first(row, "課程名稱", "科目名稱", "課名", "1"),
        "學分數": _first(row, "實得學分", "學分數", "學分", "2"),
        "修課成績": _first(row, "修課成績", "成績", "總成績", "3"),
        "call_id": _clean(row.get("科目代號")),
    }


def normalize_exemption_row(row: dict[str, str]) -> dict[str, str]:
    year = _clean(row.get("學年"))
    term = _clean(row.get("學期"))
    if year and term:
        sem = year + term
    else:
        sem = _term(_first(row, "學年學期", "學期", "0"))

    return {
        "學年學期": sem,
        "課程名稱": _first(row, "課程名稱", "科目名稱", "課名", "1"),
        "學分數": _first(row, "學分數", "學分", "實得學分", "2"),
        "抵免類型": _first(row, "抵免類型", "類型", "3"),
        "核准狀態": _first(row, "核准狀態", "核准", "狀態", "審核狀態", "4"),
        "原始備註": _first(row, "原始備註", "備註", "說明", "5"),
    }


def approved_exemption_credits(rows: Iterable[dict[str, str]]) -> float:
    total = 0.0
    for row in rows:
        status = _clean(row.get("核准狀態"))
        if status not in {"已核准", "核准", "通過"}:
            continue
        try:
            total += float(_clean(row.get("學分數")) or 0)
        except ValueError:
            continue
    return total


STUGRADE_URL = "https://catalog.cgu.edu.tw/stugrade"
EXEMPTION_TAB_TEXTS = ["抵免學分核准結果", "抵免學分", "抵免"]


def _table_matrix(table_locator) -> list[list[str]]:
    rows: list[list[str]] = []
    for row_locator in table_locator.locator("tr").all():
        cells = row_locator.locator("th,td").all_inner_texts()
        if cells:
            rows.append([_clean(cell) for cell in cells])
    return rows


def _all_table_rows(page) -> list[dict[str, str]]:
    for frame in [page, *page.frames]:
        tables = frame.locator("table")
        for index in range(tables.count()):
            rows = parse_table_rows(_table_matrix(tables.nth(index)))
            if rows:
                return rows
    return []


def extract_course_rows(page) -> list[dict[str, str]]:
    try:
        page.locator("#tab0 table").first.wait_for(state="visible", timeout=15000)
        page.wait_for_function(
            """
            () => {
                const tbody = document.querySelector('#tab0 table tbody');
                if (!tbody) return false;
                const trs = tbody.querySelectorAll('tr');
                if (trs.length === 0) return false;
                return trs[0].innerText.trim().length > 0;
            }
            """,
            timeout=15000,
        )
    except Exception:
        page.wait_for_timeout(2000)

    table_locator = page.locator("#tab0 table").first
    if table_locator.count() == 0:
        table_locator = page.locator("table").first

    if table_locator.count() == 0:
        raise RuntimeError("stugrade 已修課程表未解析到任何課程（找不到表格元素）")

    raw_matrix = _table_matrix(table_locator)
    rows = parse_table_rows(raw_matrix)
    normalized_rows = [normalize_course_row(row) for row in rows]
    filtered_rows = [row for row in normalized_rows if row["課程名稱"] and row["學分數"]]

    if not filtered_rows:
        raise RuntimeError("stugrade 已修課程表未解析到任何課程")
    return filtered_rows


def _click_exemption_tab(page) -> bool:
    for text in EXEMPTION_TAB_TEXTS:
        for frame in [page, *page.frames]:
            locator = frame.get_by_text(text, exact=False).first
            try:
                if locator.count() > 0:
                    locator.click()
                    page.wait_for_timeout(1000)
                    return True
            except Exception:
                continue
    return False


BOOKING_FIELDS = ["課程名稱", "學分數", "開課序號", "開課單位"]


def extract_booking_rows(page) -> list[dict[str, str]]:
    try:
        page.wait_for_function(
            "() => document.querySelectorAll('table tr').length > 1",
            timeout=10000,
        )
    except Exception:
        page.wait_for_timeout(1000)

    rows: list[dict[str, str]] = []
    for frame in [page, *page.frames]:
        tables = frame.locator("table")
        for i in range(tables.count()):
            raw = _table_matrix(tables.nth(i))
            parsed = parse_table_rows(raw)
            if not parsed:
                continue
            # Look for a table that contains course-like data
            header_text = " ".join(raw[0]) if raw else ""
            if not any(k in header_text for k in ["課程", "科目", "選課"]):
                continue
            for row in parsed:
                name = _first(row, "課程名稱", "科目名稱", "課名")
                credits = _first(row, "學分數", "學分")
                section = _first(row, "開課序號", "序號", "科目代號")
                dept = _first(row, "開課單位", "系所", "單位")
                if name:
                    rows.append({
                        "課程名稱": name,
                        "學分數": credits,
                        "開課序號": section,
                        "開課單位": dept,
                    })
        if rows:
            break
    return rows


def extract_exemption_rows(page) -> tuple[list[dict[str, str]], list[str]]:
    if not _click_exemption_tab(page):
        return [], ["找不到抵免學分核准結果分頁"]

    try:
        page.locator("#tab1 table").first.wait_for(state="visible", timeout=5000)
    except Exception:
        pass

    table_locator = page.locator("#tab1 table").first
    if table_locator.count() == 0:
        return [], []

    raw_matrix = _table_matrix(table_locator)
    rows = parse_table_rows(raw_matrix)
    normalized_rows = [normalize_exemption_row(row) for row in rows]

    filtered_rows = [
        row for row in normalized_rows
        if row["課程名稱"] or row["學分數"] or row.get("核准狀態")
    ]
    filtered_rows = [
        row for row in filtered_rows
        if "無資料" not in row["課程名稱"] and "無資料" not in (row.get("核准狀態") or "")
    ]
    return filtered_rows, []
