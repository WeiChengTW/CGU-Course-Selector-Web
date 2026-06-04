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
        "紅樓夢之詩詞品賞", "臺灣詩．鄉土情", "臺灣古典文學選讀", "史學名著選讀", "自然生態文學",
        "音樂與文化", "電影與音樂", "室內樂作品欣賞與實習", "殿堂之外：現代音樂與流行樂文化",
        "交響樂的世界", "弦樂欣賞", "音樂與情緒", "基礎素描", "中國繪畫入門",
        "電影與醫學的對話", "道家思想導論與導讀", "聖經與科學",
        "英美小說選讀", "商務英語溝通", "新聞英語", "國際時事閱讀與會話", "英文簡報技巧",
        "旅遊英文", "學術英文寫作", "職場英語檢定", "環境與生態", "雅思閱讀與寫作",
        "美國大眾文化與世界", "社會秩序與犯罪", "地域與文化", "思考與爭辯的藝術",
        "托福英文", "現代詩與當代文化", "寓言-經典與多元思維",
        "日文（1）", "日文（2）", "日文（3）", "德文（1）", "德文（2）", "德文（3）",
        "初階法文", "進階法文",
    ],
    "社會科學": [
        "中國近、現代史", "歷史與人物", "醫療人權與案例討論", "1960年代專題",
        "經典閱讀:<羅爾斯正義論>", "醫療與社會", "多元文化、媒體與社會", "賽局理論",
        "危機調適理論與實務", "科技倫理", "醫學、疾病與現代東亞社會", "傳染病史概論",
        "影像中的社會與文化", "管理經濟學", "財務管理與分析", "個人理財與投資",
        "法律與生活", "網路社會學", "兩性關係", "親職教育", "自我探索", "人際溝通",
        "特殊教育導論", "生涯發展與規劃", "認識銀髮族", "瘟癘瘴蠱", "生命的科學",
        "生物科技產業之認識與分析", "全球化思維的領導與決策", "媒體素養",
        "企業組織與工作倫理", "智慧財產權", "團體動力在人際互動的應用",
        "溝通技巧與領導統御", "情境模擬的創新法則", "法學緒論", "自由主義",
        "全球與兩岸政治經濟",
    ],
    "自然科學": [
        "營養與保健", "生命科學導論", "針灸學概論", "草藥的認識與應用",
        "中藥的養生保健與美容", "中醫概論", "人類性學概論", "生物技術概論",
        "自然科技與永續發展應用", "生物技術及生物資訊之發展現況",
        "趣味數學與量子計算", "大數據之旅-挑戰Kaggle", "網頁設計美學", "部落格數位生活",
        "程式寫作邏輯導論", "資料處理與應用", "借力使力人工智慧", "舉一反三人工智慧",
        "新興能源技術概論", "能源需求與供給的全球衝擊", "生命科學與工程", "生醫材料概論",
    ],
    "運算思維": [
        "人工智慧概論", "程式語言及其醫學應用", "健康應用之程式語言",
        "R程式語言入門", "R 程式語言入門", "Python程式語言", "Python 程式語言",
        "Python入門與實作", "Python 入門與實作", "Python程式入門", "Python 程式入門",
    ],
    "跨域學習與實踐": [
        "從急救案例到人生省思", "量子諧振設計", "創新設計思考", "創業知能",
        "能源與文明永續", "環境變遷與永續發展策略", "環境教育與永續發展",
        "創新、創意、創業開發課程", "正念減壓與情緒管理", "西洋文學與醫學-經典選讀",
        "服務學習與營隊活動導論(一) USR 與SDGs", "服務學習與營隊活動導論(二)活動規劃",
        "服務學習與營隊活動導論（一）USR 與 SDGs", "服務學習與營隊活動導論（二）活動規劃",
        "大學與社區連結", "身心障礙者的社區共融與永續", "身心障礙者的社區共融與永續之場域實作",
        "龜山區稻米產業多元化-清酒釀造", "臺灣戰後經濟發展與台塑企業的成長",
        "田野調查：跨領域應用與實作", "團體領導實作課程(1)", "團體領導實作課程(2)",
        "利他行為與生死迷思（1）：基礎知識", "利他行為與生死迷思（2）：場域實作",
        "長庚大學周遭的自然生態與生態調查方法", "長庚大學周遭人文景觀踏查與林地生態調查",
    ],
}

# 資工/資管/工管/工程學院學生不得選修的多元選修課程（規則：「工程、管理、智慧運算學院學生不得選修」）
_ENGINEERING_EXCLUDED_MULTI: set[str] = {
    # 人工智慧概論：無工程學院限制，不排除（其限制說明屬於課程2「程式語言及其醫學應用」）
    "R程式語言入門", "R 程式語言入門",
    "Python程式語言", "Python 程式語言",
    "Python入門與實作", "Python 入門與實作",
    "Python程式入門", "Python 程式入門",
    "大數據之旅-挑戰Kaggle",
    "網頁設計美學", "部落格數位生活", "程式寫作邏輯導論", "資料處理與應用",
}

# 以下靜態清單僅作 fallback（當 LLM 分類失敗時使用），不是主要邏輯
_CORE_DOMAINS: dict[str, list[str]] = {
    "藝術與人文思維": [
        "文學中的現代軌跡", "傳記文學選讀及寫作", "現代詩與當代文化", "寓言-經典與多元思維",
        "臺灣詩．鄉土情", "哲學與文化", "音樂的語言", "歌劇與歌劇院",
        "倫理與美學：電影與戲劇中的莎士比亞", "西洋文學概論: 古代作品選讀", "歐美戲劇",
        "北美小說、技藝與性別角色",
    ],
    "公民與社會探究": [
        "政治學與現代公民", "法學緒論", "現代公民的社會學想像", "經濟學與現代社會",
        "近代東亞的歷史變遷與發展", "社會心理學", "科技法律", "自由主義",
        "全球與兩岸政治經濟", "管理與現代社會", "腦與認知",
    ],
}


_CLASSIFY_SYSTEM = (
    "你是大學畢業規則分析助手。請嚴格依照提供的規則文件判斷課程分類，"
    "不要依賴訓練知識猜測，只輸出 JSON。"
)

_CLASSIFY_USER_TEMPLATE = """\
【任務】
請根據下方的畢業規則文件，判斷這位學生已通過的通識選修課程（校定選修/校定必修）\
屬於哪個**通識多元選修**子領域，以及學生是否有資格列入。

【說明】
通識課程分為兩大類，請嚴格區分：
1. **核心課程**（本任務不需分類）：在規則文件「核心課程」章節下的「藝術與人文思維」和「公民與社會探究」，\
   這些課程**不屬於多元選修**，不要將它們分類為多元選修。
2. **多元選修課程**（本任務要分類）：在規則文件「多元選修課程」章節下的 5 個子領域：\
   人文藝術、社會科學、自然科學、運算思維、跨域學習與實踐。

請只對「多元選修課程」章節中出現的課程輸出分類，核心課程章節的課程請輸出 grad_category="通識核心課程"（不填 domain，讓系統自動處理）。

【學生基本資訊】
{student_info}

【需分類的課程（已通過的校定選修/校定必修）】
{course_list}

【畢業規則文件】
{rules_text}

【輸出格式（只輸出 JSON）】
{{
  "classifications": [
    {{
      "course_name": "課程名稱",
      "credits": 2,
      "grad_category": "通識多元選修",
      "domain": "社會科學",
      "eligible": true,
      "ineligible_reason": ""
    }},
    ...
  ]
}}

重要規則：
1. eligible=false 僅在規則**明確寫明**「X學院學生不得選修」且確定適用於該學生時使用，\
   若不確定請設 eligible=true。
2. 若課程不在多元選修課程清單中，將 grad_category 設為「通識核心課程」或「校定必修」，不填 domain。
3. 【OCR 格式注意】「運算思維領域」中課程 1「人工智慧概論」無任何學院限制；\
   「工程、管理、智慧運算學院學生不得選修」是課程 2「程式語言及其醫學應用」的限制，\
   因 PDF 多欄排版 OCR 可能顯示錯位，請依上述正確解讀。
"""


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
    req = urllib.request.Request(
        endpoint, data=json.dumps(data).encode("utf-8"), headers=headers, method="POST"
    )

    print("正在進行課程分類（Phase 1）...", flush=True)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
                content = raw["choices"][0]["message"]["content"]
                parsed = json.loads(extract_json(content))
                result = parsed.get("classifications", [])
                if isinstance(result, list) and result:
                    print(f"課程分類完成：{len(result)} 門課", flush=True)
                    return result
        except Exception as e:
            if attempt < 2:
                print(f"課程分類失敗（第{attempt+1}次）：{e}，重試...", file=sys.stderr)
                time.sleep(2)
            else:
                print(f"課程分類失敗，將使用靜態清單 fallback：{e}", file=sys.stderr)
    return []


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

    prompt = f"""請根據以下提供的修課紀錄 CSV 資料、修課統計摘要，以及多份畢業規則 Markdown 檔案，為這位學生進行畢業學分分析。

【強制規則 — 違反將產生錯誤結果】
1. 「預計算分析」區塊已用 Python 精確計算，**所有數字請直接採用，禁止自行重新計算或覆蓋**。
2. 通識多元選修：已通過學分 = **{_multi_total_str}學分**，領域數 = **{_multi_domain_str}個**，需求 = {_multi_req_cr}學分/{_multi_req_d}個領域，缺口 = **{_multi_gap_str}學分**。請將此數字直接填入 JSON。
{f'3. {_excluded_note}' if _excluded_note else '3. （無排除課程）'}
4. 進行中課程不算「已完成」，要在 requirements 中說明「含進行中X學分」。
5. **必須**回傳一個純 JSON 物件，不要有任何其他 Markdown 文字或解釋。
6. 只能根據提供的 CSV 與規則判斷，不確定時請列在 manual_review_items，不要亂猜。

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
    print(f"已儲存分析結果至 {report_json_path}")

    md_content = render_markdown_report(
        report_data, rules_md_paths=rules_md_paths, model=model
    )
    ensure_parent(report_md_path)
    report_md_path.write_text(md_content, encoding="utf-8")
    print(f"已儲存 Markdown 報告至 {report_md_path}")
