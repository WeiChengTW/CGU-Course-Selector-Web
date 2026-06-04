from __future__ import annotations

import json
import re
import time
import httpx
from pathlib import Path

from app.config import get_logger
from app.lib.graduation.indexer import query_rules
from app.lib.graduation.report import render_markdown_report
from app.lib.graduation.utils import ensure_parent, extract_json

from app.lib.graduation.llm_client import classify_courses_llm
from app.lib.graduation.calculators import _build_precomputed_context
from app.lib.graduation.report_builder import (
    validate_report_schema,
    load_course_records,
    validate_report_grounding,
    _apply_precomputed_overrides,
)
from app.lib.graduation.static_data import _ANALYZE_SYSTEM, _ANALYZE_USER_TEMPLATE

logger = get_logger(__name__)


def call_llm_analyzer(
    csv_path: Path,
    rules_md_paths: list[Path],
    summary: str,
    base_url: str,
    api_key: str,
    model: str,
    report_md_path: Path,
    report_json_path: Path,
    report_raw_path: Path,
    rules_index_path: Path | None = None,
    honor_program: bool | None = None,
) -> None:
    csv_text = csv_path.read_text(encoding="utf-8-sig") if csv_path.exists() else ""
    course_records = load_course_records(csv_path)

    rules_index: dict = {}
    if rules_index_path and rules_index_path.exists():
        rules_index = json.loads(rules_index_path.read_text(encoding="utf-8"))

    # 取得規則文字（Phase 1 分類和 Phase 3 報告都需要）
    rules_md_text_parts = []
    for p in rules_md_paths:
        if p.exists():
            rules_md_text_parts.append(f"--- 規則文件：{p.name} ---\n{p.read_text(encoding='utf-8')}")
    rules_md_text = "\n".join(rules_md_text_parts)

    if rules_index:
        categories = {row.get("課程類別", "").strip() for row in course_records}
        categories.discard("")
        rules_section = query_rules(rules_index, categories)
    else:
        rules_section = rules_md_text

    # Phase 1：讓 LLM 根據規則文件分類學生課程（不計算，只分類）
    classifications = classify_courses_llm(
        records=course_records,
        rules_text=rules_md_text,
        base_url=base_url,
        api_key=api_key,
        model=model,
        honor_program=bool(honor_program),
    )

    # Phase 2：Python 用分類結果精確計算學分
    precomputed_context = _build_precomputed_context(
        course_records,
        rules_index=rules_index or None,
        honor_program=honor_program,
        classifications=classifications or None,
    )

    # Extract key precomputed values to embed directly in the prompt
    _multi_match = re.search(r"多元選修合計：([\d.]+)學分 / (\d+) 個領域", precomputed_context)
    _multi_total_str = _multi_match.group(1) if _multi_match else "?"
    _multi_domain_str = _multi_match.group(2) if _multi_match else "?"
    _multi_req = re.search(r"通識多元選修（規則：(\d+)學分，至少(\d+)個領域）", precomputed_context)
    _multi_req_cr = _multi_req.group(1) if _multi_req else "11"
    _multi_req_d = _multi_req.group(2) if _multi_req else "3"
    _multi_gap = re.search(r"多元選修尚缺 ([\d.]+) 學分", precomputed_context)
    _multi_gap_str = _multi_gap.group(1) if _multi_gap else "?"
    _excluded_note = ""
    if "不得列入多元選修" in precomputed_context:
        m = re.search(r"⚠ 以下課程不得列入多元選修.*?(?=\n■|\Z)", precomputed_context, re.DOTALL)
        if m:
            _excluded_note = m.group(0).strip()

    excluded_note_line = f'3. {_excluded_note}' if _excluded_note else '3. （無排除課程）'

    prompt = _ANALYZE_USER_TEMPLATE.format(
        multi_total_str=_multi_total_str,
        multi_domain_str=_multi_domain_str,
        multi_req_cr=_multi_req_cr,
        multi_req_d=_multi_req_d,
        multi_gap_str=_multi_gap_str,
        excluded_note_line=excluded_note_line,
        precomputed_context=precomputed_context,
        csv_text=csv_text,
        summary=summary,
        rules_section=rules_section,
    )

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    data = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": _ANALYZE_SYSTEM,
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
    }

    base_url = base_url.rstrip("/")
    endpoint = (
        base_url if base_url.endswith("/chat/completions") else f"{base_url}/chat/completions"
    )

    logger.info("llm_analysis_calling", model=model, endpoint=endpoint)

    json_str = ""
    content = ""
    for attempt in range(3):
        try:
            logger.info("llm_analysis_waiting", attempt=attempt+1, max_attempts=3)
            with httpx.Client(timeout=300.0) as client:
                response = client.post(endpoint, json=data, headers=headers)
                raw_response = response.text
                if not raw_response.strip():
                    raise ValueError("API 回傳空白內容")
                result = response.json()
                content = result["choices"][0]["message"]["content"]
                json_str = extract_json(content)
                break
        except httpx.HTTPStatusError as e:
            if e.response.status_code in {401, 403, 404}:
                raise
            if attempt < 2:
                logger.warning("llm_analysis_http_error", code=e.response.status_code, attempt=attempt+1)
                time.sleep(2)
            else:
                raise
        except Exception as e:
            if attempt < 2:
                logger.warning("llm_analysis_error", error=str(e), attempt=attempt+1)
                time.sleep(2)
            else:
                raise

    report_data = json.loads(json_str)
    schema_errors = validate_report_schema(report_data)
    if schema_errors:
        ensure_parent(report_raw_path)
        report_raw_path.write_text(content, encoding="utf-8")
        raise ValueError("LLM 回傳 JSON schema 不符合預期：" + "；".join(schema_errors))

    # Phase 3 後處理：用 Python precomputed 結果覆寫多元選修欄位（防止 LLM 算錯）
    _apply_precomputed_overrides(
        report_data, precomputed_context, course_records,
        rules_index or None, honor_program, classifications or None
    )

    validate_report_grounding(report_data, csv_path)

    ensure_parent(report_json_path)
    report_json_path.write_text(
        json.dumps(report_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info("llm_analysis_result_saved", path=str(report_json_path))

    md_content = render_markdown_report(
        report_data, rules_md_paths=rules_md_paths, model=model
    )
    ensure_parent(report_md_path)
    report_md_path.write_text(md_content, encoding="utf-8")
    logger.info("llm_analysis_md_saved", path=str(report_md_path))