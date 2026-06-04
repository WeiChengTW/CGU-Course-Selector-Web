from __future__ import annotations

import csv
import re
from pathlib import Path

from app.lib.graduation.calculators import (
    _build_requirement_course_details,
    _extract_domains_from_index,
    _matching_detail_key,
    _normalize_requirement_from_detail,
    _credit_value,
)


REQUIRED_REPORT_KEYS = [
    "status",
    "recognized_credits",
    "required_credits",
    "missing_credits",
    "one_sentence_summary",
    "requirements",
    "missing_items",
    "detailed_checks",
    "limited_or_excluded_courses",
    "manual_review_items",
    "next_semester_recommendations",
]


def validate_report_schema(report_data: dict) -> list[str]:
    errors = []
    if not isinstance(report_data, dict):
        return ["LLM 回傳內容不是 JSON object。"]
    for key in REQUIRED_REPORT_KEYS:
        if key not in report_data:
            errors.append(f"缺少必要欄位：{key}")
    list_keys = [
        "requirements",
        "missing_items",
        "limited_or_excluded_courses",
        "manual_review_items",
        "next_semester_recommendations",
    ]
    for key in list_keys:
        if key in report_data and not isinstance(report_data[key], list):
            errors.append(f"欄位 {key} 必須是 list。")
    if "detailed_checks" in report_data and not isinstance(report_data["detailed_checks"], dict):
        errors.append("欄位 detailed_checks 必須是 object。")
    return errors


def load_course_records(csv_path: Path) -> list[dict[str, str]]:
    if not csv_path.exists():
        return []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def append_manual_review(report_data: dict, item: str, reason: str, evidence: str) -> None:
    report_data.setdefault("manual_review_items", [])
    report_data["manual_review_items"].append(
        {"item": item, "reason": reason, "evidence": evidence}
    )


def validate_report_grounding(report_data: dict, csv_path: Path) -> None:
    course_names = {
        row.get("課程名稱", "").strip() for row in load_course_records(csv_path)
    }
    course_names.discard("")
    if not course_names:
        return

    containers = []
    containers.extend(report_data.get("limited_or_excluded_courses", []))
    containers.extend(report_data.get("completed_items", []))

    for item in containers:
        if not isinstance(item, dict):
            continue
        candidate = str(item.get("course", item.get("item", ""))).strip()
        if not candidate or any(
            keyword in candidate
            for keyword in ("領域", "門檻", "學分", "選修", "必修", "學程", "摘要", "統計")
        ):
            continue
        if not re.search(r"[0-9A-Za-z(（)]", candidate):
            continue
        if candidate not in course_names and not any(
            candidate in name or name in candidate for name in course_names
        ):
            append_manual_review(
                report_data,
                candidate,
                "報告將此項目描述為已完成/已修，但在修課紀錄找不到對應課程名稱。",
                "課程名稱比對驗證",
            )


def _apply_precomputed_overrides(
    report_data: dict,
    precomputed_context: str,
    records: list[dict],
    rules_index: dict | None,
    honor_program: bool | None,
    classifications: list[dict] | None = None,
) -> None:
    """Use deterministic CSV-derived values to normalize LLM report arithmetic and details."""
    details = _build_requirement_course_details(records, rules_index, classifications)
    total_detail = details["畢業總學分"]

    dyn = _extract_domains_from_index(rules_index) if rules_index else {}
    required_total = float(dyn.get("total_required_credits") or report_data.get("required_credits") or 128)
    report_data["passed_credits"] = total_detail["passed_credits"]
    report_data["in_progress_credits"] = total_detail["in_progress_credits"]
    report_data["recognized_credits"] = total_detail["total_counted_credits"]
    report_data["required_credits"] = required_total
    report_data["missing_credits"] = max(0, required_total - total_detail["total_counted_credits"])

    for req in report_data.get("requirements", []):
        category = str(req.get("category", ""))
        key = _matching_detail_key(category)
        if key and key in details:
            default_required = required_total if key == "畢業總學分" else 0.0
            _normalize_requirement_from_detail(req, details[key], default_required)
        elif "通識" in category and "多元" not in category:
            req["course_details"] = details["通識"]
            if str(req.get("missing", "")).strip() in {"", "無"}:
                req["status"] = "已完成"
                req["progress_percent"] = 100

        if "多元" in category and classifications:
            _apply_multi_elective_requirement(req, precomputed_context)

    _remove_resolved_missing_items(report_data)
    if report_data["missing_credits"] > 0:
        report_data["status"] = "尚不可畢業"
    elif total_detail["in_progress_credits"] > 0:
        report_data["status"] = "進行中"
    elif any(req.get("status") in {"未完成", "需人工確認"} for req in report_data.get("requirements", [])):
        report_data["status"] = "需人工確認"
    else:
        report_data["status"] = "符合畢業資格"


def _apply_multi_elective_requirement(req: dict, precomputed_context: str) -> None:
    m_total = re.search(r"多元選修合計：([\d.]+)學分(?:（已對應領域 [\d.]+學分）)?/ (\d+) 個", precomputed_context)
    m_req = re.search(r"通識多元選修（規則：(\d+)學分，至少(\d+)個領域）", precomputed_context)
    m_gap = re.search(r"多元選修尚缺 ([\d.]+) 學分", precomputed_context)
    if not m_total:
        return

    correct_total = float(m_total.group(1))
    correct_domains = int(m_total.group(2))
    req_cr = int(m_req.group(1)) if m_req else 11
    req_d = int(m_req.group(2)) if m_req else 3
    gap = max(0, float(m_gap.group(1)) if m_gap else (req_cr - correct_total))
    is_done = correct_total >= req_cr and correct_domains >= req_d
    req["status"] = "已完成" if is_done else "未完成"
    req["completed"] = f"{correct_total:g}學分（{correct_domains}個領域）"
    req["missing"] = "無" if is_done else f"尚缺{gap:g}學分"
    req["progress_percent"] = min(100, round((correct_total / req_cr * 100) if req_cr > 0 else 0))
    req.setdefault("course_details", {})
    req["course_details"].setdefault("passed_credits", correct_total)
    req["course_details"].setdefault("in_progress_credits", 0)
    req["course_details"].setdefault("total_counted_credits", correct_total)


def _remove_resolved_missing_items(report_data: dict) -> None:
    resolved_categories = {
        str(req.get("category", ""))
        for req in report_data.get("requirements", [])
        if req.get("status") in {"已完成", "進行中"}
        and str(req.get("missing", "")).strip() in {"", "無", "無確定學分缺口；需完成進行中課程"}
    }

    def keep(item: dict) -> bool:
        category = str(item.get("category", ""))
        if any(category and category in req_cat for req_cat in resolved_categories):
            return False
        if _credit_value(item.get("credits", 0)) <= 0 and "領域" not in str(item.get("item", "")):
            return False
        return True

    report_data["missing_items"] = [
        item for item in report_data.get("missing_items", [])
        if not isinstance(item, dict) or keep(item)
    ]