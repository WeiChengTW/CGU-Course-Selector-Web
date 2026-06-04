from __future__ import annotations

import json
import time
import httpx

from app.config import get_logger
from app.lib.graduation.utils import extract_json
from app.lib.graduation.static_data import _CLASSIFY_SYSTEM, _CLASSIFY_USER_TEMPLATE

logger = get_logger(__name__)


def classify_courses_llm(
    records: list[dict[str, str]],
    rules_text: str,
    base_url: str,
    api_key: str,
    model: str,
    honor_program: bool = False,
) -> list[dict]:
    """
    Phase 1: 讓 LLM 依規則文件將學生已通過課程分類。
    回傳 classifications list，每筆含 course_name/credits/grad_category/domain/eligible/ineligible_reason。
    失敗時回傳空 list（呼叫端應 fallback 到靜態清單）。
    """
    passed = [r for r in records if r.get("是否通過", "") == "True"]
    if not passed:
        return []

    # 只需分類「通識相關」課程：校定選修、校定必修（通識）
    # 系定必修/系定選修已在 CSV 明確標注，不需要 LLM 分類
    gen_ed_categories = {"校定選修", "校定必修"}
    courses_to_classify = [
        r for r in passed
        if r.get("課程類別", "") in gen_ed_categories
    ]
    if not courses_to_classify:
        return []

    # 推斷學生身份（從系定課程名稱）
    dept_courses = [r.get("課程名稱", "") for r in records if r.get("課程類別", "") in ("系定必修", "系定選修")]
    student_info_lines = [f"- 榮譽學程：{'是' if honor_program else '否'}"]
    if dept_courses:
        student_info_lines.append(f"- 系所課程範例（供判斷學院歸屬）：{', '.join(dept_courses[:8])}")

    course_lines = "\n".join(
        f"- {r['課程名稱']}（{r.get('學分', '?')} 學分，CSV類別：{r.get('課程類別', '?')}，學年：{r.get('學年學期', '?')}）"
        for r in courses_to_classify
    )

    prompt = _CLASSIFY_USER_TEMPLATE.format(
        student_info="\n".join(student_info_lines),
        course_list=course_lines,
        rules_text=rules_text,  # 完整規則文字，不截斷
    )

    base_url = base_url.rstrip("/")
    endpoint = (
        base_url if base_url.endswith("/chat/completions") else f"{base_url}/chat/completions"
    )
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    data = {
        "model": model,
        "messages": [
            {"role": "system", "content": _CLASSIFY_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
    }
    logger.info("classification_phase1_started")
    for attempt in range(3):
        try:
            with httpx.Client(timeout=180.0) as client:
                response = client.post(endpoint, json=data, headers=headers)
                raw = response.json()
                content = raw["choices"][0]["message"]["content"]
                parsed = json.loads(extract_json(content))
                result = parsed.get("classifications", [])
                if isinstance(result, list) and result:
                    logger.info("classification_phase1_done", courses=len(result))
                    return result
        except Exception as e:
            if attempt < 2:
                logger.warning("classification_phase1_retry", attempt=attempt+1, error=str(e))
                time.sleep(2)
            else:
                logger.warning("classification_phase1_fallback", error=str(e))
    return []