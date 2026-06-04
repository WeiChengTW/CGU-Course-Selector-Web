from __future__ import annotations

import json
import re

from app.lib.graduation.static_data import (
    _ELECTIVE_DOMAINS,
    _MULTI_ELECTIVE_DOMAINS,
    _CORE_DOMAINS,
    _ENGINEERING_EXCLUDED_MULTI,
)


def _safe_int(value, default: int) -> int:
    """Convert value to int, stripping trailing non-numeric chars (e.g. '30學分' → 30)."""
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        m = re.match(r"^\s*(\d+)", str(value))
        return int(m.group(1)) if m else default


def _extract_domains_from_index(index: dict) -> dict:
    result: dict = {
        "elective_domains": {},
        "elective_min_credits": 30,
        "elective_min_domain_credits": 12,
        "elective_required_domains": 2,
        "multi_elective_domains": {},
        "multi_elective_min_credits": 11,
        "multi_elective_min_domains": 3,
        "core_domains": {},
        "core_min_credits": 12,
        "total_required_credits": 128,
    }

    sys_el = index.get("系選修", {})
    if isinstance(sys_el, dict):
        result["elective_min_credits"] = _safe_int(sys_el.get("最低學分"), 30)
        regulation = str(sys_el.get("規定", ""))
        m = re.search(r"每領域至少(\d+)學分", regulation)
        if m:
            result["elective_min_domain_credits"] = _safe_int(m.group(1), 12)
        domain_map = sys_el.get("領域課程對照", {})
        if isinstance(domain_map, dict):
            for domain, courses in domain_map.items():
                if isinstance(courses, list):
                    clean = [re.sub(r"\([^)]*\)$", "", c).strip().rstrip("*") for c in courses]
                    result["elective_domains"][domain] = [c for c in clean if c]

    multi = index.get("多元選修課程", {})
    if isinstance(multi, dict):
        # 支援 "學分要求" 或 "總學分要求" 兩種 key
        cr_val = multi.get("學分要求") or multi.get("總學分要求") or multi.get("必修學分", 11)
        result["multi_elective_min_credits"] = _safe_int(cr_val, 11)
        # 新格式：子領域 list
        for sub in multi.get("子領域", []):
            if not isinstance(sub, dict):
                continue
            dname = sub.get("領域名稱", "")
            if not dname:
                continue
            courses: list[str] = []
            for section in ("可選課程", "必選課程"):
                for c in sub.get(section, []):
                    n = c.get("名稱", "") if isinstance(c, dict) else str(c)
                    if n:
                        courses.append(n)
            result["multi_elective_domains"][dname] = courses
        # 舊格式相容：領域名稱 list + 課程限制 dict（無課程清單，略過）
        if not result["multi_elective_domains"]:
            for dname in multi.get("領域", []):
                if isinstance(dname, str):
                    result["multi_elective_domains"][dname] = []

    core = index.get("核心課程", {})
    if isinstance(core, dict):
        cr_val = core.get("學分要求") or core.get("總學分要求") or core.get("必修學分", 12)
        result["core_min_credits"] = _safe_int(cr_val, 12)
        # 新格式：子領域 list
        for sub in core.get("子領域", []):
            if not isinstance(sub, dict):
                continue
            dname = sub.get("領域名稱", "")
            if not dname:
                continue
            courses = []
            for c in sub.get("可選課程", []):
                n = c.get("名稱", "") if isinstance(c, dict) else str(c)
                if n:
                    courses.append(n)
            result["core_domains"][dname] = courses
        # 舊格式相容：領域 dict（含 "學分" key，無課程清單）
        if not result["core_domains"]:
            for dname, info in multi.get("領域", {}).items() if isinstance(multi.get("領域"), dict) else []:
                result["core_domains"][dname] = []

    total = index.get("畢業總學分", {})
    if isinstance(total, dict):
        cr = total.get("總學分") or total.get("學分要求") or total.get("必修學分")
        if cr:
            result["total_required_credits"] = _safe_int(cr, 128)

    return result


def _build_classification_maps(
    classifications: list[dict],
    honor_courses_taken: set[str],
) -> tuple[dict[str, list[tuple[str, float]]], dict[str, list[tuple[str, float]]], list[tuple[str, float, str]]]:
    """
    從 LLM Phase 1 分類結果建立 core_domain_map、multi_domain_map、excluded_from_multi。
    回傳 (core_domain_map, multi_domain_map, excluded_from_multi)。
    """
    core_domain_map: dict[str, list[tuple[str, float]]] = {}
    multi_domain_map: dict[str, list[tuple[str, float]]] = {}
    excluded_from_multi: list[tuple[str, float, str]] = []
    already_placed: set[str] = set()  # 防止同一門課被重複計算

    for item in classifications:
        name = str(item.get("course_name", "")).strip()
        credits = float(item.get("credits", 0) or 0)
        category = str(item.get("grad_category", ""))
        domain = str(item.get("domain", "")).strip()
        eligible = item.get("eligible", True)
        reason = str(item.get("ineligible_reason", ""))

        if not name or credits <= 0:
            continue

        if not eligible:
            if "多元" in category or "核心" in category:
                excluded_from_multi.append((name, credits, reason or "規則限制不得列入（請人工確認）"))
            continue

        if category == "通識核心課程":
            # 核心課程由靜態清單處理，Phase 1 只需標記「已見過」避免重複計算
            already_placed.add(f"核心:{name}")
        elif category == "通識多元選修" and domain:
            key = f"多元:{name}"
            if key not in already_placed:
                already_placed.add(key)
                multi_domain_map.setdefault(domain, []).append((name, credits))

    # 榮譽學程抵免（若 LLM 未分類到才補上）
    if "批判性思考：品德與幸福" in honor_courses_taken:
        if "核心:批判性思考：品德與幸福" not in already_placed:
            core_domain_map.setdefault("藝術與人文思維", []).append(("批判性思考：品德與幸福(榮譽學程抵免)", 3.0))
    if "青年領袖論壇" in honor_courses_taken:
        if "多元:青年領袖論壇" not in already_placed:
            multi_domain_map.setdefault("跨域學習與實踐(榮譽學程抵免)", []).append(("青年領袖論壇", 2.0))

    return core_domain_map, multi_domain_map, excluded_from_multi


def _build_precomputed_context(
    records: list[dict[str, str]],
    rules_index: dict | None = None,
    honor_program: bool | None = None,
    classifications: list[dict] | None = None,
) -> str:
    if rules_index:
        dyn = _extract_domains_from_index(rules_index)
        elective_domains = dyn["elective_domains"] or _ELECTIVE_DOMAINS
        elective_min_credits = dyn["elective_min_credits"]
        elective_min_domain_credits = dyn["elective_min_domain_credits"]
        elective_required_domains = dyn["elective_required_domains"]
        # 只有在 index 提取到實際課程名稱時才用動態結果，否則 fallback 到靜態清單
        _dyn_multi = dyn["multi_elective_domains"]
        multi_elective_domains = (
            _dyn_multi if any(courses for courses in _dyn_multi.values())
            else _MULTI_ELECTIVE_DOMAINS
        )
        _dyn_core = dyn["core_domains"]
        core_domains = (
            _dyn_core if any(courses for courses in _dyn_core.values())
            else _CORE_DOMAINS
        )
        multi_elective_min_credits = dyn["multi_elective_min_credits"]
        multi_elective_min_domains = dyn["multi_elective_min_domains"]
        core_min_credits = dyn["core_min_credits"]
        REQUIRED_TOTAL = float(dyn["total_required_credits"])
    else:
        elective_domains = _ELECTIVE_DOMAINS
        elective_min_credits = 30
        elective_min_domain_credits = 12
        elective_required_domains = 2
        multi_elective_domains = _MULTI_ELECTIVE_DOMAINS
        multi_elective_min_credits = 11
        multi_elective_min_domains = 3
        core_domains = _CORE_DOMAINS
        core_min_credits = 12
        REQUIRED_TOTAL = 128.0

    in_progress = [
        r for r in records
        if r.get("成績", "").strip().upper() in {"", "I"} and r.get("是否通過", "") == "False"
    ]
    english_intensive = [r for r in records if "英文專修學習" in r.get("課程名稱", "")]
    honors_courses = {"批判性思考：品德與幸福", "青年領袖論壇"}

    if honor_program is None:
        is_honors = len(english_intensive) > 0 or any(
            r.get("課程名稱", "") in honors_courses for r in records
        )
    else:
        is_honors = honor_program

    system_electives_all = [
        r for r in records if r.get("課程類別", "") == "系定選修"
    ]
    domain_credits: dict[str, float] = {d: 0.0 for d in elective_domains}
    domain_credits_inprogress: dict[str, float] = {d: 0.0 for d in elective_domains}
    domain_courses: dict[str, list[str]] = {d: [] for d in elective_domains}
    assigned: set[str] = set()

    for r in system_electives_all:
        name = r.get("課程名稱", "").strip()
        credits = float(r.get("學分", 0) or 0)
        passed = r.get("是否通過", "") == "True"
        inprogress = r.get("成績", "").strip().upper() in {"", "I"} and r.get("是否通過", "") == "False"
        if not passed and not inprogress:
            continue
        matched_domains = [
            d for d, courses in elective_domains.items()
            if any(name == c or c in name or name in c for c in courses)
        ]
        for d in matched_domains:
            key = f"{d}:{name}"
            if key not in assigned:
                assigned.add(key)
                if passed:
                    domain_credits[d] += credits
                    domain_courses[d].append(f"{name}({credits:g})")
                else:
                    domain_credits_inprogress[d] += credits
                    domain_courses[d].append(f"{name}({credits:g},進行中)")

    domain_total = {d: domain_credits[d] + domain_credits_inprogress[d] for d in elective_domains}
    domains_over_12 = {d: c for d, c in domain_total.items() if c >= elective_min_domain_credits}
    domains_partial = {d: c for d, c in domain_total.items() if 0 < c < elective_min_domain_credits}
    domain_meets_requirement = len(domains_over_12) >= elective_required_domains

    multi_elective_passed = [
        r for r in records
        if r.get("是否通過", "") == "True"
        and r.get("課程名稱", "") not in {"英文專修學習"}
        and (
            r.get("課程類別", "") == "校定選修"
            or (
                r.get("課程類別", "") == "校定必修"
                and any(
                    r.get("課程名稱", "") == c or c in r.get("課程名稱", "")
                    for courses in list(core_domains.values()) + list(multi_elective_domains.values())
                    for c in courses
                )
            )
        )
    ]
    honors_courses_taken: set[str] = {
        r.get("課程名稱", "") for r in records
        if r.get("課程名稱", "") in honors_courses
        and r.get("是否通過", "") == "True"
    }

    if classifications:
        # Phase 1 分類結果可用：多元選修用 LLM 分類，核心課程仍用靜態清單（更可靠）
        _, multi_domain_map, excluded_from_multi = _build_classification_maps(
            classifications, honors_courses_taken
        )
        # 核心課程：靜態清單比對（課程固定，不易誤判）
        core_domain_map = {}
        for r in multi_elective_passed:
            name = r.get("課程名稱", "").strip()
            credits = float(r.get("學分", 0) or 0)
            for domain, courses in core_domains.items():
                if any(name == c or c in name or name in c for c in courses):
                    core_domain_map.setdefault(domain, []).append((name, credits))
        if "批判性思考：品德與幸福" in honors_courses_taken:
            core_domain_map.setdefault("藝術與人文思維", []).append(("批判性思考：品德與幸福(榮譽學程抵免)", 3.0))
    else:
        # Fallback：用靜態清單比對（規則異動時可能不準）
        excluded_from_multi = []
        core_domain_map = {}
        multi_domain_map = {}
        for r in multi_elective_passed:
            name = r.get("課程名稱", "").strip()
            credits = float(r.get("學分", 0) or 0)
            if name in _ENGINEERING_EXCLUDED_MULTI:
                excluded_from_multi.append((name, credits, "工程、管理、智慧運算學院學生不得列入多元選修學分（規則明定）"))
                continue
            for domain, courses in core_domains.items():
                if any(name == c or c in name or name in c for c in courses):
                    core_domain_map.setdefault(domain, []).append((name, credits))
            for domain, courses in multi_elective_domains.items():
                if any(name == c or c in name or name in c for c in courses):
                    multi_domain_map.setdefault(domain, []).append((name, credits))

        if "批判性思考：品德與幸福" in honors_courses_taken:
            core_domain_map.setdefault("藝術與人文思維", []).append(("批判性思考：品德與幸福(榮譽學程抵免)", 3.0))
        if "青年領袖論壇" in honors_courses_taken:
            multi_domain_map.setdefault("跨域學習與實踐(榮譽學程抵免)", []).append(("青年領袖論壇", 2.0))

    core_total = sum(c for courses in core_domain_map.values() for _, c in courses)
    multi_total = sum(c for courses in multi_domain_map.values() for _, c in courses)
    multi_domains_count = len(multi_domain_map)

    # Names already classified as core-only (must not be double-counted as multi-elective)
    core_matched_names: set[str] = {
        name for courses in core_domain_map.values() for name, _ in courses
        if "榮譽學程抵免" not in name
    }
    multi_matched_names: set[str] = {
        name for courses in multi_domain_map.values() for name, _ in courses
        if "榮譽學程抵免" not in name
    }
    # 校定選修 courses that matched neither core nor multi domain lists.
    # Their domain is unknown but they are still 通識 elective credits.
    unmatched_multi = [
        r for r in multi_elective_passed
        if r.get("課程名稱", "").strip() not in core_matched_names
        and r.get("課程名稱", "").strip() not in multi_matched_names
    ]
    unmatched_credits = sum(float(r.get("學分", 0) or 0) for r in unmatched_multi)
    # Correct total: domain-matched multi credits + unmatched (non-core) credits
    multi_total_all = multi_total + unmatched_credits

    lines = ["【預計算分析（請直接採用，不需重新推斷）】"]
    lines.append(f"\n■ 學生身份：{'榮譽學程學生（使用者勾選）' if is_honors else '一般學生'}")
    lines.append(f"\n■ 英文領域（通識）：")
    lines.append(f"  - 英文專修學習 共 {len(english_intensive)} 筆")
    if is_honors and len(english_intensive) >= 6:
        lines.append("  - 結論：榮譽學程規定6次英文專修學習即完整抵免通識英文領域6學分。")
    elif is_honors:
        lines.append(f"  - 結論：目前只有 {len(english_intensive)} 次，榮譽學程要求6次，尚不足。")

    # 抵免學分
    exemption_records = [r for r in records if r.get("成績", "") == "抵免"]
    if exemption_records:
        lines.append(f"\n■ 抵免學分（已核准）：")
        for r in exemption_records:
            name = r.get("課程名稱", "")
            credits = r.get("學分", "?")
            category = r.get("課程類別", "抵免類型未知")
            lines.append(f"  - {name}（{credits}學分，類別：{category}）")
        total_exempt = sum(float(r.get("學分", 0) or 0) for r in exemption_records)
        lines.append(f"  → 結論：共 {total_exempt:g} 學分抵免已核准，計入對應類別要求。")
    else:
        lines.append(f"\n■ 抵免學分：無核准抵免紀錄。")

    lines.append(f"\n■ 進行中課程：")
    if in_progress:
        for r in in_progress:
            lines.append(f"  - {r.get('學年學期','')} {r.get('課程名稱','')} {r.get('學分','')}學分（{r.get('課程類別','')}）")
        lines.append("  → 以上課程不應標記為「已完成」，應標記為「進行中」。")
    else:
        lines.append("  - 無進行中課程。")

    lines.append(f"\n■ 系定選修領域分析（規則：最低{elective_min_credits}學分，至少{elective_required_domains}個領域各≥{elective_min_domain_credits}學分）：")
    for d, courses in domain_courses.items():
        cr_done = domain_credits[d]
        cr_prog = domain_credits_inprogress[d]
        cr_total = cr_done + cr_prog
        if cr_total == 0:
            status = "✗ 未修"
        elif cr_total >= elective_min_domain_credits:
            status = f"✓ 達標"
        else:
            status = "△ 部分"
        lines.append(f"  {d}：{cr_done:g}已通過 + {cr_prog:g}進行中 = {cr_total:g}學分 {status}")
    if domain_meets_requirement:
        met = ", ".join(f"{d}({c:g}cr)" for d, c in domains_over_12.items())
        lines.append(f"  → 結論：預計滿足{elective_required_domains}領域≥{elective_min_domain_credits}學分要求（{met}）。")
    else:
        lines.append(f"  → 結論：目前只有{len(domains_over_12)}個領域達標，尚未滿足要求。")

    lines.append(f"\n■ 通識核心課程（規則：{core_min_credits}學分）：")
    for domain, courses in core_domain_map.items():
        total = sum(c for _, c in courses)
        lines.append(f"  {domain}：{total:g}學分")
    lines.append(f"  核心課程合計：{core_total:g}學分（需{core_min_credits}學分）")

    _multi_status = "未完成" if (multi_total < multi_elective_min_credits or multi_domains_count < multi_elective_min_domains) else "已完成"
    _multi_missing_desc = (
        f"尚缺{multi_elective_min_credits - multi_total:g}學分"
        if multi_total < multi_elective_min_credits
        else (f"領域數不足（需{multi_elective_min_domains}，目前{multi_domains_count}）" if multi_domains_count < multi_elective_min_domains else "無")
    )
    _multi_domain_detail = "；".join(
        f"{d}={sum(c for _, c in cs):g}學分({', '.join(n for n, _ in cs)})"
        for d, cs in multi_domain_map.items()
    )
    _multi_evidence = f"Python預計算：{_multi_domain_detail or '無符合課程'}"
    if excluded_from_multi:
        _excl = "；".join(f"{n}({cr:g}學分)已排除" for n, cr, _ in excluded_from_multi)
        _multi_evidence += f"；排除課程：{_excl}"

    lines.append(f"\n■ 通識多元選修（規則：{multi_elective_min_credits}學分，至少{multi_elective_min_domains}個領域）：")
    for domain, courses in multi_domain_map.items():
        total = sum(c for _, c in courses)
        course_list = ", ".join(f"{n}({c:g})" for n, c in courses)
        lines.append(f"  {domain}：{total:g}學分（{course_list}）")
    if unmatched_multi:
        lines.append("  未對應領域課程（仍計入學分）：")
        for r in unmatched_multi:
            lines.append(f"    - {r.get('課程名稱','')}（{r.get('學分','?')}學分，{r.get('課程類別','')}）")
    lines.append(f"  多元選修合計：{multi_total_all:g}學分（已對應領域 {multi_total:g}學分）/ {multi_domains_count} 個已辨識領域")
    if excluded_from_multi:
        lines.append("  ⚠ 以下課程不得列入多元選修（規則排除）：")
        for name, cr, reason in excluded_from_multi:
            lines.append(f"    - {name}（{cr:g}學分）：{reason}")
    if multi_total_all < multi_elective_min_credits:
        lines.append(f"  → 結論：多元選修尚缺 {multi_elective_min_credits - multi_total_all:g} 學分。")
    elif multi_domains_count < multi_elective_min_domains:
        lines.append(f"  → 結論：學分足夠但已辨識領域數不足（需{multi_elective_min_domains}，目前{multi_domains_count}），需人工確認未對應課程的領域。")
    else:
        lines.append(f"  → 結論：多元選修已達標。")
    # 強制 JSON 片段：LLM 必須直接複製此段到 requirements 中，不得修改數字
    _multi_json = json.dumps({
        "category": "通識多元選修",
        "status": _multi_status,
        "required": f"{multi_elective_min_credits}學分（至少{multi_elective_min_domains}個領域）",
        "completed": f"{multi_total:g}學分（{multi_domains_count}個領域）",
        "missing": _multi_missing_desc,
        "evidence": _multi_evidence,
    }, ensure_ascii=False)
    lines.append(f"\n  ★ 通識多元選修 requirements 必填 JSON（直接複製，數字不得更改）：")
    lines.append(f"  {_multi_json}")

    passed_credits = sum(
        float(r.get("學分", 0) or 0) for r in records if r.get("是否通過", "") == "True"
    )
    inprogress_credits = sum(float(r.get("學分", 0) or 0) for r in in_progress)
    total_expected_credits = passed_credits + inprogress_credits
    total_gap = REQUIRED_TOTAL - total_expected_credits

    confirmed_gaps: list[str] = []
    if not domain_meets_requirement:
        confirmed_gaps.append(f"系選修：領域達標數不足（需{elective_required_domains}個，目前{len(domains_over_12)}個）")
    if multi_total_all < multi_elective_min_credits:
        confirmed_gaps.append(f"通識多元選修：差 {multi_elective_min_credits - multi_total_all:g} 學分")
    elif multi_domains_count < multi_elective_min_domains and not unmatched_multi:
        confirmed_gaps.append(f"通識多元選修：領域數不足（需{multi_elective_min_domains}，目前{multi_domains_count}）")

    credits_note = f"目前 {total_expected_credits:g} / {REQUIRED_TOTAL:g}"
    if total_gap <= 0:
        credits_note = f"總學分已達標（{total_expected_credits:g} ≥ {REQUIRED_TOTAL:g}）"

    lines.append(f"\n■ 確認缺口總結（{credits_note}）：")
    if confirmed_gaps:
        for g in confirmed_gaps:
            lines.append(f"  - {g}")
    else:
        lines.append("  - 無確定缺口")
    lines.append("  ★ manual_review_items 只放「資料不足無法判斷」的項目。")

    return "\n".join(lines)


def _credit_value(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _format_credit(value: float) -> str:
    return f"{value:g}"


def _record_status(record: dict) -> str:
    if record.get("是否通過", "") == "True":
        return "已通過"
    score = record.get("成績", "").strip().upper()
    if score == "" or score == "I":
        return "進行中"
    return "未採計"


def _course_detail(record: dict) -> dict:
    return {
        "term": record.get("學年學期", ""),
        "name": record.get("課程名稱", ""),
        "credits": _credit_value(record.get("學分", 0)),
        "score": record.get("成績", ""),
        "status": _record_status(record),
        "category": record.get("課程類別", ""),
    }


def _summarize_detail_courses(records: list[dict], *, include_categories: set[str] | None = None) -> dict:
    courses = []
    failed_courses = []
    passed_credits = 0.0
    in_progress_credits = 0.0
    failed_credits = 0.0

    for record in records:
        if include_categories is not None and record.get("課程類別", "") not in include_categories:
            continue
        detail = _course_detail(record)
        if detail["status"] == "已通過":
            passed_credits += detail["credits"]
            courses.append(detail)
        elif detail["status"] == "進行中":
            in_progress_credits += detail["credits"]
            courses.append(detail)
        else:
            failed_credits += detail["credits"]
            failed_courses.append(detail)

    total_counted = passed_credits + in_progress_credits
    return {
        "passed_credits": passed_credits,
        "in_progress_credits": in_progress_credits,
        "total_counted_credits": total_counted,
        "failed_credits": failed_credits,
        "courses": courses,
        "failed_courses": failed_courses,
    }


def _extract_required_credits(value, default: float = 0.0) -> float:
    match = re.search(r"[\d.]+", str(value or ""))
    return float(match.group(0)) if match else default


def _status_from_credits(passed: float, in_progress: float, required: float) -> str:
    if required <= 0:
        return "需人工確認"
    if passed >= required:
        return "已完成"
    if passed + in_progress >= required:
        return "進行中"
    return "未完成"


def _missing_from_credits(passed: float, in_progress: float, required: float) -> str:
    total = passed + in_progress
    if required <= 0:
        return "需人工確認"
    if passed >= required:
        return "無"
    if total >= required:
        return "無確定學分缺口；需完成進行中課程"
    return f"尚缺{_format_credit(required - total)}學分"


def _completed_text(detail: dict) -> str:
    passed = detail["passed_credits"]
    in_progress = detail["in_progress_credits"]
    total = detail["total_counted_credits"]
    if in_progress > 0:
        return f"{_format_credit(passed)}學分已通過 + {_format_credit(in_progress)}學分進行中 = {_format_credit(total)}學分"
    return f"{_format_credit(passed)}學分"


def _build_system_elective_domains(records: list[dict], rules_index: dict | None) -> list[dict]:
    if rules_index:
        dyn = _extract_domains_from_index(rules_index)
        elective_domains = dyn["elective_domains"] or _ELECTIVE_DOMAINS
    else:
        elective_domains = _ELECTIVE_DOMAINS

    domains = {name: {"name": name, "passed_credits": 0.0, "in_progress_credits": 0.0, "courses": []} for name in elective_domains}
    assigned: set[str] = set()
    for record in records:
        if record.get("課程類別", "") != "系定選修":
            continue
        detail = _course_detail(record)
        if detail["status"] == "未採計":
            continue
        name = detail["name"]
        for domain, course_names in elective_domains.items():
            if not any(name == c or c in name or name in c for c in course_names):
                continue
            key = f"{domain}:{name}:{detail['term']}"
            if key in assigned:
                continue
            assigned.add(key)
            if detail["status"] == "已通過":
                domains[domain]["passed_credits"] += detail["credits"]
            else:
                domains[domain]["in_progress_credits"] += detail["credits"]
            domains[domain]["courses"].append(detail)

    result = []
    for domain in domains.values():
        domain["total_counted_credits"] = domain["passed_credits"] + domain["in_progress_credits"]
        if domain["total_counted_credits"] > 0:
            result.append(domain)
    return result


def _build_multi_elective_domains(records: list[dict], classifications: list[dict] | None) -> list[dict]:
    """Build domain breakdown for 通識多元選修 from LLM classifications."""
    if not classifications:
        return []

    # Map course name → (domain, eligible)
    course_map: dict[str, tuple[str, bool]] = {}
    for cls in classifications:
        if cls.get("grad_category") == "通識多元選修" and cls.get("domain"):
            course_map[cls["course_name"]] = (cls["domain"], cls.get("eligible", True))

    domains: dict[str, dict] = {}
    for record in records:
        cat = record.get("課程類別", "")
        if cat not in {"校定選修", "校定必修"}:
            continue
        detail = _course_detail(record)
        if detail["status"] == "未採計":
            continue
        name = detail["name"]
        if name not in course_map:
            continue
        domain, eligible = course_map[name]
        if not eligible:
            continue

        if domain not in domains:
            domains[domain] = {"name": domain, "passed_credits": 0.0, "in_progress_credits": 0.0, "courses": []}

        if detail["status"] == "已通過":
            domains[domain]["passed_credits"] += detail["credits"]
        else:
            domains[domain]["in_progress_credits"] += detail["credits"]
        domains[domain]["courses"].append(detail)

    result = []
    for domain in domains.values():
        domain["total_counted_credits"] = domain["passed_credits"] + domain["in_progress_credits"]
        if domain["total_counted_credits"] > 0:
            result.append(domain)
    return result


def _build_requirement_course_details(
    records: list[dict], rules_index: dict | None = None, classifications: list[dict] | None = None
) -> dict[str, dict]:
    details = {
        "畢業總學分": _summarize_detail_courses(records),
        "系定必修": _summarize_detail_courses(records, include_categories={"系定必修"}),
        "系定選修": _summarize_detail_courses(records, include_categories={"系定選修"}),
        "校定必修": _summarize_detail_courses(records, include_categories={"校定必修"}),
        "校定選修": _summarize_detail_courses(records, include_categories={"校定選修"}),
        "通識": _summarize_detail_courses(records, include_categories={"校定必修", "校定選修"}),
        "通識多元選修": _summarize_detail_courses(records, include_categories={"校定選修", "校定必修"}),
    }
    details["系定選修"]["domains"] = _build_system_elective_domains(records, rules_index)
    details["通識多元選修"]["domains"] = _build_multi_elective_domains(records, classifications)
    return details


def _matching_detail_key(category: str) -> str | None:
    if "總學分" in category:
        return "畢業總學分"
    if "系定必修" in category or "系必修" in category:
        return "系定必修"
    if "系定選修" in category or "系選修" in category:
        return "系定選修"
    if "通識" in category and "多元" in category:
        return "通識多元選修"
    if "通識" in category and "多元" not in category:
        return None
    if "校定必修" in category:
        return "校定必修"
    if "校定選修" in category:
        return "校定選修"
    return None


def _normalize_requirement_from_detail(req: dict, detail: dict, required_default: float = 0.0) -> None:
    required = _extract_required_credits(req.get("required"), required_default)
    passed = detail["passed_credits"]
    in_progress = detail["in_progress_credits"]
    total = detail["total_counted_credits"]
    req["course_details"] = detail
    req["progress_percent"] = min(100, round((total / required * 100) if required > 0 else 0))
    req["completed"] = _completed_text(detail)
    if required > 0:
        req["status"] = _status_from_credits(passed, in_progress, required)
        req["missing"] = _missing_from_credits(passed, in_progress, required)
    elif str(req.get("missing", "")).strip() in {"", "無"}:
        req["status"] = "已完成"