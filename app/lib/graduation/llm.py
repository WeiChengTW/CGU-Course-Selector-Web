from __future__ import annotations

import csv
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from app.lib.graduation.indexer import query_rules
from app.lib.graduation.report import render_markdown_report
from app.lib.graduation.utils import ensure_parent, extract_json

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


_ELECTIVE_DOMAINS: dict[str, list[str]] = {
    "資訊系統設計": [
        "Unix程式設計", "物件導向軟體設計", "作業系統實務", "平行程式設計", "編譯器設計",
        "通訊系統", "嵌入式軟體設計", "資料庫設計", "校外實習", "軟硬體協同設計", "雲端系統",
    ],
    "資訊應用技術": [
        "訊號與系統", "資料庫系統設計", "網頁程式設計", "計算機圖學", "多媒體資訊概論",
        "生物統計", "人工智慧", "校外實習", "樣型識別", "資料庫設計", "生醫資訊概論",
        "機器學習", "雲端系統", "機器學習與其醫學應用", "深度學習與Python實作", "醫學影像處理",
    ],
    "計算機網路技術": [
        "資料庫系統設計", "網頁程式設計", "網路應用軟體設計", "Unix程式設計", "通訊系統",
        "平行程式設計", "校外實習", "高等計算機網路", "物聯網", "網路安全與管理", "雲端系統",
    ],
    "人工智慧": [
        "智慧感測與識別", "大數據應用", "人工智慧應用於工業4.0", "深度學習概論",
        "人工智慧專題", "自然語言技術與實作", "Unix程式設計",
    ],
}

_MULTI_ELECTIVE_DOMAINS: dict[str, list[str]] = {
    "人文藝術": [
        "現代詩", "詩詞選讀", "中文寫作", "古典短篇小說選讀", "張愛玲小說選讀", "文學與人生",
        "音樂與文化", "電影與音樂", "道家思想導論與導讀", "英美小說選讀", "商務英語溝通",
        "國際時事閱讀與會話", "英文簡報技巧", "學術英文寫作", "職場英語檢定",
        "美國大眾文化與世界", "社會秩序與犯罪", "思考與爭辯的藝術",
        "日文（1）", "日文（2）", "日文（3）", "德文（1）", "德文（2）", "德文（3）",
    ],
    "社會科學": [
        "中國近、現代史", "歷史與人物", "醫療人權與案例討論", "賽局理論",
        "科技倫理", "管理經濟學", "財務管理與分析", "個人理財與投資", "法律與生活",
        "網路社會學", "兩性關係", "親職教育", "自我探索", "人際溝通", "生涯發展與規劃",
        "全球化思維的領導與決策", "媒體素養", "企業組織與工作倫理", "智慧財產權",
    ],
    "自然科學": [
        "營養與保健", "生命科學導論", "生物技術概論", "自然科技與永續發展應用",
        "趣味數學與量子計算", "大數據之旅-挑戰Kaggle", "網頁設計美學", "部落格數位生活",
        "程式寫作邏輯導論", "資料處理與應用", "借力使力人工智慧", "舉一反三人工智慧",
        "新興能源技術概論", "能源需求與供給的全球衝擊",
    ],
    "運算思維": [
        "人工智慧概論", "程式語言及其醫學應用", "健康應用之程式語言",
        "R 程式語言入門", "Python 程式語言", "Python 入門與實作", "Python 程式入門",
    ],
    "跨域學習與實踐": [
        "從急救案例到人生省思", "創新設計思考", "創業知能", "能源與文明永續",
        "環境變遷與永續發展策略", "環境教育與永續發展", "正念減壓與情緒管理",
        "服務學習與營隊活動導論（一）USR 與 SDGs", "服務學習與營隊活動導論（二）活動規劃",
        "大學與社區連結", "身心障礙者的社區共融與永續",
    ],
}

_CORE_DOMAINS: dict[str, list[str]] = {
    "藝術與人文思維": [
        "文學中的現代軌跡", "傳記文學選讀及寫作", "現代詩與當代文化", "寓言-經典與多元思維",
        "哲學與文化", "音樂的語言", "歌劇與歌劇院", "西洋文學概論: 古代作品選讀",
    ],
    "公民與社會探究": [
        "政治學與現代公民", "法學緒論", "現代公民的社會學想像", "經濟學與現代社會",
        "近代東亞的歷史變遷與發展", "社會心理學", "科技法律", "自由主義",
        "全球與兩岸政治經濟", "管理與現代社會", "腦與認知",
    ],
}


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
        result["elective_min_credits"] = int(sys_el.get("最低學分", 30))
        regulation = str(sys_el.get("規定", ""))
        m = re.search(r"每領域至少(\d+)學分", regulation)
        if m:
            result["elective_min_domain_credits"] = int(m.group(1))
        domain_map = sys_el.get("領域課程對照", {})
        if isinstance(domain_map, dict):
            for domain, courses in domain_map.items():
                if isinstance(courses, list):
                    clean = [re.sub(r"\([^)]*\)$", "", c).strip().rstrip("*") for c in courses]
                    result["elective_domains"][domain] = [c for c in clean if c]

    multi = index.get("多元選修課程", {})
    if isinstance(multi, dict):
        result["multi_elective_min_credits"] = int(multi.get("學分要求", 11))
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

    core = index.get("核心課程", {})
    if isinstance(core, dict):
        result["core_min_credits"] = int(core.get("學分要求", 12))
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

    total = index.get("畢業總學分", {})
    if isinstance(total, dict) and "總學分" in total:
        result["total_required_credits"] = int(total["總學分"])

    return result


def _build_precomputed_context(
    records: list[dict[str, str]],
    rules_index: dict | None = None,
    honor_program: bool | None = None,
) -> str:
    if rules_index:
        dyn = _extract_domains_from_index(rules_index)
        elective_domains = dyn["elective_domains"] or _ELECTIVE_DOMAINS
        elective_min_credits = dyn["elective_min_credits"]
        elective_min_domain_credits = dyn["elective_min_domain_credits"]
        elective_required_domains = dyn["elective_required_domains"]
        multi_elective_domains = dyn["multi_elective_domains"] or _MULTI_ELECTIVE_DOMAINS
        multi_elective_min_credits = dyn["multi_elective_min_credits"]
        multi_elective_min_domains = dyn["multi_elective_min_domains"]
        core_domains = dyn["core_domains"] or _CORE_DOMAINS
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
        if r.get("成績", "").strip() == "" and r.get("是否通過", "") == "False"
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
        inprogress = r.get("成績", "").strip() == "" and r.get("是否通過", "") == "False"
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

    core_domain_map: dict[str, list[tuple[str, float]]] = {}
    multi_domain_map: dict[str, list[tuple[str, float]]] = {}
    for r in multi_elective_passed:
        name = r.get("課程名稱", "").strip()
        credits = float(r.get("學分", 0) or 0)
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

    lines = ["【預計算分析（請直接採用，不需重新推斷）】"]
    lines.append(f"\n■ 學生身份：{'榮譽學程學生（使用者勾選）' if is_honors else '一般學生'}")
    lines.append(f"\n■ 英文領域（通識）：")
    lines.append(f"  - 英文專修學習 共 {len(english_intensive)} 筆")
    if is_honors and len(english_intensive) >= 6:
        lines.append("  - 結論：榮譽學程規定6次英文專修學習即完整抵免通識英文領域6學分。")
    elif is_honors:
        lines.append(f"  - 結論：目前只有 {len(english_intensive)} 次，榮譽學程要求6次，尚不足。")

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

    lines.append(f"\n■ 通識多元選修（規則：{multi_elective_min_credits}學分，至少{multi_elective_min_domains}個領域）：")
    for domain, courses in multi_domain_map.items():
        total = sum(c for _, c in courses)
        lines.append(f"  {domain}：{total:g}學分")
    lines.append(f"  多元選修合計：{multi_total:g}學分 / {multi_domains_count} 個領域")
    if multi_total < multi_elective_min_credits:
        lines.append(f"  → 結論：多元選修尚缺 {multi_elective_min_credits - multi_total:g} 學分。")
    elif multi_domains_count < multi_elective_min_domains:
        lines.append(f"  → 結論：學分足夠但領域數不足（需{multi_elective_min_domains}，目前{multi_domains_count}）。")
    else:
        lines.append(f"  → 結論：多元選修已達標。")

    passed_credits = sum(
        float(r.get("學分", 0) or 0) for r in records if r.get("是否通過", "") == "True"
    )
    inprogress_credits = sum(float(r.get("學分", 0) or 0) for r in in_progress)
    total_expected_credits = passed_credits + inprogress_credits
    total_gap = REQUIRED_TOTAL - total_expected_credits

    confirmed_gaps: list[str] = []
    if not domain_meets_requirement:
        confirmed_gaps.append(f"系選修：領域達標數不足（需{elective_required_domains}個，目前{len(domains_over_12)}個）")
    if multi_total < multi_elective_min_credits:
        confirmed_gaps.append(f"通識多元選修：差 {multi_elective_min_credits - multi_total:g} 學分")
    elif multi_domains_count < multi_elective_min_domains:
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

    precomputed_context = _build_precomputed_context(
        course_records, rules_index=rules_index or None, honor_program=honor_program
    )

    if rules_index:
        categories = {row.get("課程類別", "").strip() for row in course_records}
        categories.discard("")
        rules_section = query_rules(rules_index, categories)
    else:
        rules_text = []
        for p in rules_md_paths:
            if p.exists():
                rules_text.append(f"--- 規則文件：{p.name} ---\n{p.read_text(encoding='utf-8')}")
        rules_section = "\n".join(rules_text)

    prompt = f"""請根據以下提供的修課紀錄 CSV 資料、修課統計摘要，以及多份畢業規則 Markdown 檔案，為這位學生進行畢業學分分析。

【要求】
1. 只能根據提供的 CSV 與 Markdown 規則判斷，不確定時請列在「需要人工確認」，不要亂猜。
2. **「預計算分析」區塊中的結論請直接採用，不要與其相矛盾。**
3. 進行中課程不算「已完成」，要在 requirements 中說明「含進行中X學分」。
4. **必須**回傳一個純 JSON 物件，不要有任何其他 Markdown 文字或解釋。

```json
{{
  "status": "尚不可畢業",
  "recognized_credits": 122,
  "required_credits": 128,
  "missing_credits": 6,
  "one_sentence_summary": "目前尚缺系定必修1學分、系選修3學分、通識多元2學分。",
  "requirements": [
    {{
      "category": "系定必修",
      "status": "未完成",
      "required": "63學分",
      "completed": "62學分（含進行中1學分）",
      "missing": "軟硬體專題(3) 1學分",
      "evidence": "畢業學分.md：系定必修63學分"
    }}
  ],
  "missing_items": [
    {{
      "priority": "high",
      "category": "系定必修",
      "item": "軟硬體專題(3)",
      "credits": 1,
      "recommended_action": "大四修習或依規定確認是否可抵修"
    }}
  ],
  "detailed_checks": {{
    "compulsory": [],
    "elective": [],
    "general_education": [],
    "honors_or_special": []
  }},
  "limited_or_excluded_courses": [],
  "manual_review_items": [],
  "next_semester_recommendations": []
}}
```

---
【輸入資料】

<預計算分析>
{precomputed_context}
</預計算分析>

<修課紀錄 CSV>
{csv_text}
</修課紀錄 CSV>

<修課統計摘要>
{summary}
</修課統計摘要>

<畢業規則>
{rules_section}
</畢業規則>
"""

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    data = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "你是一個專業的大學畢業學分分析助手。請只輸出 JSON 格式資料，並請務必使用繁體中文（zh-TW）撰寫內容。",
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
    }

    base_url = base_url.rstrip("/")
    endpoint = (
        base_url if base_url.endswith("/chat/completions") else f"{base_url}/chat/completions"
    )

    print(f"正在呼叫 LLM 分析 ({model}) 於 {endpoint} ...")
    req = urllib.request.Request(
        endpoint, data=json.dumps(data).encode("utf-8"), headers=headers, method="POST"
    )

    json_str = ""
    content = ""
    for attempt in range(3):
        try:
            print(f"等待 LLM 回應中（第 {attempt + 1}/3 次）...", flush=True)
            with urllib.request.urlopen(req, timeout=300) as response:
                raw_response = response.read().decode("utf-8")
                if not raw_response.strip():
                    raise ValueError("API 回傳空白內容")
                result = json.loads(raw_response)
                content = result["choices"][0]["message"]["content"]
                json_str = extract_json(content)
                break
        except urllib.error.HTTPError as e:
            error_body = ""
            try:
                error_body = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            if e.code in {401, 403, 404}:
                raise
            if attempt < 2:
                print(f"LLM 呼叫失敗 (HTTP {e.code})，重試 ({attempt + 1}/3)...", file=sys.stderr)
                time.sleep(2)
            else:
                raise
        except Exception as e:
            if attempt < 2:
                print(f"LLM 呼叫失敗：{e}，重試...", file=sys.stderr)
                time.sleep(2)
            else:
                raise

    report_data = json.loads(json_str)
    schema_errors = validate_report_schema(report_data)
    if schema_errors:
        ensure_parent(report_raw_path)
        report_raw_path.write_text(content, encoding="utf-8")
        raise ValueError("LLM 回傳 JSON schema 不符合預期：" + "；".join(schema_errors))

    validate_report_grounding(report_data, csv_path)

    ensure_parent(report_json_path)
    report_json_path.write_text(
        json.dumps(report_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"已儲存分析結果至 {report_json_path}")

    md_content = render_markdown_report(
        report_data, rules_md_paths=rules_md_paths, model=model
    )
    ensure_parent(report_md_path)
    report_md_path.write_text(md_content, encoding="utf-8")
    print(f"已儲存 Markdown 報告至 {report_md_path}")
