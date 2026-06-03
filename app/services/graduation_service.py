"""畢業進度服務 - 讀取報告與執行分析"""

from __future__ import annotations

import csv
import json
import os
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.config import BASE_DIR

DEFAULT_LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://air.cgu.edu.tw/cgullmapi/v1")
DEFAULT_LLM_MODEL = os.getenv("LLM_MODEL", "gpt-5.4-mini")
DEFAULT_RULES_DIR = BASE_DIR / "data" / "rules"

STATUS_FILE = "graduation_status.json"
REPORT_FILE = "graduation_report.json"
GRAD_PDF_FILE = "graduation_pdf.pdf"
HONOR_PDF_FILE = "graduation_honor_pdf.pdf"
MERGED_CSV_FILE = "graduation_merged.csv"
RULES_MD_DIR = "graduation_rules_md"
RULES_INDEX_FILE = "graduation_rules_index.json"


class GraduationService:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.report_path = data_dir / REPORT_FILE
        self.status_path = data_dir / STATUS_FILE

    def get_report(self) -> Optional[dict]:
        if not self.report_path.exists():
            return None
        with self.report_path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def has_report(self) -> bool:
        return self.report_path.exists()

    def get_status(self) -> dict:
        if not self.status_path.exists():
            return {"status": "none"}
        with self.status_path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def write_status(self, status: str, message: str = "") -> None:
        data = {"status": status, "message": message, "updated_at": datetime.now().isoformat()}
        self.status_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def reset(self) -> None:
        for fname in (REPORT_FILE, STATUS_FILE, MERGED_CSV_FILE, RULES_INDEX_FILE):
            p = self.data_dir / fname
            if p.exists():
                p.unlink()
        for fname in (GRAD_PDF_FILE, HONOR_PDF_FILE):
            p = self.data_dir / fname
            if p.exists():
                p.unlink()
        rules_md = self.data_dir / RULES_MD_DIR
        if rules_md.exists():
            import shutil
            shutil.rmtree(rules_md)


def _merge_course_csv(session_dir: Path) -> Path:
    """Merge taken_courses.csv + courses_detail.csv into a combined CSV for LLM analysis."""
    taken_path = session_dir / "taken_courses.csv"
    detail_path = session_dir / "courses_detail.csv"
    output_path = session_dir / MERGED_CSV_FILE

    taken_rows: list[dict] = []
    if taken_path.exists():
        with taken_path.open("r", encoding="utf-8-sig", newline="") as f:
            taken_rows = list(csv.DictReader(f))

    detail_map: dict[str, dict] = {}
    if detail_path.exists():
        with detail_path.open("r", encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                name = row.get("課程名稱", "").strip()
                term = (row.get("學年學期", "") or "").replace("-", "")
                if name:
                    detail_map[f"{term}:{name}"] = row

    def _is_passed(score: str) -> bool:
        if not score:
            return False
        score = score.strip()
        if score == "S":
            return False
        if score in ("P", "通過", "及格"):
            return True
        try:
            return float(score) >= 60
        except ValueError:
            return False

    merged: list[dict] = []
    for row in taken_rows:
        name = row.get("課程名稱", "").strip()
        term = (row.get("學年學期", "") or "").replace("-", "")
        score = row.get("修課成績", "").strip()
        credits_raw = row.get("學分數", "") or row.get("學分", "")

        detail = detail_map.get(f"{term}:{name}") or detail_map.get(f":{name}") or {}
        credits = detail.get("學分", "") or credits_raw
        category = detail.get("課程類別", "")
        passed = _is_passed(score)

        merged.append({
            "學年學期": term,
            "課程名稱": name,
            "學分": credits,
            "成績": score,
            "是否通過": str(passed),
            "課程類別": category,
        })

    with output_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["學年學期", "課程名稱", "學分", "成績", "是否通過", "課程類別"]
        )
        writer.writeheader()
        writer.writerows(merged)

    return output_path


def run_graduation_analysis(
    session_dir: Path,
    honor_program: bool,
    api_key: str | None,
) -> None:
    """Background task: run full graduation analysis pipeline."""
    svc = GraduationService(session_dir)

    try:
        from app.lib.graduation.rules import convert_rule_pdfs
        from app.lib.graduation.indexer import build_rules_index
        from app.lib.graduation.report import summarize_courses
        from app.lib.graduation.llm import call_llm_analyzer
        from app.lib.graduation.utils import get_llm_api_key

        effective_api_key = api_key or get_llm_api_key()
        if not effective_api_key:
            svc.write_status("error", "未提供 LLM API Key，請在表單中填入或在 .env 設定 CGU_LLM_API_KEY")
            return

        base_url = DEFAULT_LLM_BASE_URL
        model = DEFAULT_LLM_MODEL

        # 1. Collect PDF paths
        svc.write_status("analyzing", "正在轉換 PDF 規則文件...")
        pdf_paths: list[Path] = []

        grad_pdf = session_dir / GRAD_PDF_FILE
        if grad_pdf.exists():
            pdf_paths.append(grad_pdf)

        if honor_program:
            honor_pdf = session_dir / HONOR_PDF_FILE
            if honor_pdf.exists():
                pdf_paths.append(honor_pdf)
            else:
                default_honor = DEFAULT_RULES_DIR / "榮譽學程學生手冊_112入學適用.pdf"
                if default_honor.exists():
                    pdf_paths.append(default_honor)

        default_gen_ed = DEFAULT_RULES_DIR / "112學年度下學期通識課程表.pdf"
        if default_gen_ed.exists():
            pdf_paths.append(default_gen_ed)

        if not pdf_paths:
            svc.write_status("error", "找不到任何規則 PDF 文件，請重新上傳")
            return

        # 2. Convert PDFs to Markdown
        rules_md_dir = session_dir / RULES_MD_DIR
        rules_md_paths = convert_rule_pdfs(pdf_paths, rules_md_dir)
        if not rules_md_paths:
            svc.write_status("error", "PDF 轉換失敗，請確認檔案格式正確")
            return

        # 3. Build rules index
        svc.write_status("analyzing", "正在建立規則索引（此步驟可能需要 1-2 分鐘）...")
        rules_index_path = session_dir / RULES_INDEX_FILE
        build_rules_index(rules_md_paths, rules_index_path, model, base_url, effective_api_key)

        # 4. Merge course CSV
        svc.write_status("analyzing", "正在準備修課資料...")
        merged_csv = _merge_course_csv(session_dir)

        # 5. Generate course summary
        from app.lib.graduation.report import summarize_courses
        summary = summarize_courses(merged_csv)

        # 6. Call LLM
        svc.write_status("analyzing", "正在進行 LLM 畢業學分分析（此步驟可能需要 1-2 分鐘）...")
        call_llm_analyzer(
            csv_path=merged_csv,
            rules_md_paths=rules_md_paths,
            summary=summary,
            base_url=base_url,
            api_key=effective_api_key,
            model=model,
            report_md_path=session_dir / "graduation_report.md",
            report_json_path=session_dir / REPORT_FILE,
            report_raw_path=session_dir / "graduation_report_raw.txt",
            rules_index_path=rules_index_path,
            honor_program=honor_program,
        )

        svc.write_status("done", "分析完成")

    except Exception as e:
        error_msg = str(e)
        print(f"畢業分析失敗：{traceback.format_exc()}")
        svc.write_status("error", f"分析失敗：{error_msg[:200]}")
