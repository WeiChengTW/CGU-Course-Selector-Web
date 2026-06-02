"""畢業進度服務 - 讀取 graduation_report.json"""

import json
from pathlib import Path
from typing import Optional


class GraduationService:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.report_path = data_dir / "graduation_report.json"

    def get_report(self) -> Optional[dict]:
        """讀取畢業報告"""
        if not self.report_path.exists():
            return None
        with self.report_path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def has_report(self) -> bool:
        """檢查是否有報告"""
        return self.report_path.exists()