from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from app.lib.graduation.utils import markdown_cell


def summarize_courses(csv_path: Path) -> str:
    if not csv_path.exists():
        return "找不到修課紀錄 CSV 檔案。"

    courses = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        courses = list(csv.DictReader(f))

    total_credits = 0.0
    zero_credit_courses = []
    category_counts: dict[str, float] = {}
    name_counts: dict[str, int] = {}

    for row in courses:
        try:
            c = float(row.get("學分", "0") or "0")
        except ValueError:
            c = 0.0

        total_credits += c
        if c == 0:
            zero_credit_courses.append(row.get("課程名稱", ""))

        cat = row.get("課程類別", "未知")
        category_counts[cat] = category_counts.get(cat, 0.0) + c

        name = row.get("課程名稱", "未知")
        name_counts[name] = name_counts.get(name, 0) + 1

    summary = [
        "### 修課資料摘要",
        f"- 總學分: {total_credits:g}",
        "",
        "#### 依課程類別加總",
    ]
    for cat, val in category_counts.items():
        summary.append(f"- {cat}: {val:g} 學分")

    summary.append("")
    summary.append("#### 重複修課 (重修或同名)")
    duplicates = {name: count for name, count in name_counts.items() if count > 1}
    if duplicates:
        for name, count in duplicates.items():
            summary.append(f"- {name}: {count} 次")
    else:
        summary.append("無")

    return "\n".join(summary)


def render_markdown_report(
    data: dict,
    *,
    csv_path: Path | None = None,
    rules_md_paths: list[Path] | None = None,
    model: str | None = None,
) -> str:
    lines = ["# 畢業學分檢查報告\n"]
    lines.append(f"> 產生時間：{datetime.now().isoformat(timespec='seconds')}")
    if model:
        lines.append(f"> 使用模型：{markdown_cell(model)}")
    if rules_md_paths:
        lines.append(f"> 規則來源：{markdown_cell(', '.join(p.name for p in rules_md_paths))}")
    lines.append("> 注意：本報告由 LLM 根據提供資料分析，正式畢業資格仍以系辦/教務處認定為準。\n")

    lines.append("## 1. 一句話結論")
    lines.append(
        f"目前{data.get('status', '未知')}，已認列 {data.get('recognized_credits', 0)} / {data.get('required_credits', 0)} 學分，尚缺 {data.get('missing_credits', 0)} 學分。"
    )
    lines.append(f"{data.get('one_sentence_summary', '')}\n")

    lines.append("## 2. 缺口總表")
    lines.append("| 優先級 | 類別 | 缺少項目 | 學分 | 建議動作 |")
    lines.append("|---|---|---:|---:|---|")
    for item in data.get("missing_items", []):
        lines.append(
            f"| {markdown_cell(item.get('priority', ''))} | {markdown_cell(item.get('category', ''))} | {markdown_cell(item.get('item', ''))} | {markdown_cell(item.get('credits', ''))} | {markdown_cell(item.get('recommended_action', ''))} |"
        )
    lines.append("")

    lines.append("## 3. 完成狀況總表")
    lines.append("| 類別 | 要求 | 已完成 | 缺少 | 狀態 |")
    lines.append("|---|---|---|---|---|")
    for req in data.get("requirements", []):
        lines.append(
            f"| {markdown_cell(req.get('category', ''))} | {markdown_cell(req.get('required', ''))} | {markdown_cell(req.get('completed', ''))} | {markdown_cell(req.get('missing', ''))} | {markdown_cell(req.get('status', ''))} |"
        )
    lines.append("")

    return "\n".join(lines)
