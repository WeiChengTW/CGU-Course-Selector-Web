"""課程服務 - 讀取已修課程並提供檢查功能"""

import csv
from pathlib import Path


class CourseService:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.csv_path = data_dir / "taken_courses.csv"
        self._courses_cache = None
        self._passed_names_cache = None

    def get_courses(self) -> list[dict]:
        """讀取已修課程 CSV"""
        if self._courses_cache is not None:
            return self._courses_cache

        if not self.csv_path.exists():
            self._courses_cache = []
            return []

        with self.csv_path.open("r", encoding="utf-8-sig", newline="") as f:
            self._courses_cache = list(csv.DictReader(f))
        return self._courses_cache

    def _get_name(self, course: dict) -> str:
        return (course.get("課程名稱") or course.get("CCOURSENAME") or "").strip()

    def _get_credits(self, course: dict) -> str:
        return (course.get("學分數") or course.get("學分") or course.get("CREDITS") or "").strip()

    def _get_score(self, course: dict) -> str:
        return (course.get("修課成績") or "").strip()

    def _is_passed(self, score: str) -> bool:
        """判斷成績是否通過（60分以上或特殊通過標記）"""
        if not score:
            return False

        score = score.strip().upper()

        if score in ('S', 'I'):
            return False

        # 特殊通過標記
        if score in ('P', '通過', '及格'):
            return True

        # 嘗試解析數字
        try:
            num = float(score)
            return num >= 60
        except ValueError:
            return False

    def get_passed_course_names(self) -> set[str]:
        """取得已通過課程名稱集合（學分已拿到）"""
        if self._passed_names_cache is not None:
            return self._passed_names_cache

        courses = self.get_courses()
        self._passed_names_cache = set()

        for c in courses:
            name = self._get_name(c)
            score = self._get_score(c)

            if name and self._is_passed(score):
                self._passed_names_cache.add(name)

        return self._passed_names_cache

    def get_all_course_names(self) -> set[str]:
        """取得所有已修課程名稱（包含未通過）"""
        courses = self.get_courses()
        return {self._get_name(c) for c in courses if self._get_name(c)}

    def check_course_status(self, course_name: str) -> dict:
        """
        檢查課程狀態
        回傳: {
            "status": "passed" | "failed" | "in_progress" | "not_taken",
            "score": 成績（如有）,
            "credits": 學分數（如有）
        }
        """
        courses = self.get_courses()
        course_name = course_name.strip()

        matches = []
        for c in courses:
            taken_name = self._get_name(c)

            # 比對課程名稱（支援部分匹配）
            if course_name == taken_name or course_name in taken_name:
                matches.append(c)

        for c in matches:
            score = self._get_score(c)
            if self._is_passed(score):
                return {"status": "passed", "score": score, "credits": self._get_credits(c)}

        for c in matches:
            score = self._get_score(c)
            if not score or score.upper() == "I":
                return {"status": "in_progress", "score": score or None, "credits": self._get_credits(c)}

        if matches:
            c = matches[0]
            return {"status": "failed", "score": self._get_score(c), "credits": self._get_credits(c)}

        return {"status": "not_taken", "score": None, "credits": None}

    def get_taken_courses_info(self) -> dict:
        """取得已修課程資訊（供前端使用）"""
        courses = self.get_courses()
        passed_names = self.get_passed_course_names()
        all_names = self.get_all_course_names()

        # 計算總學分（只計算通過的）
        total_passed_credits = 0
        for c in courses:
            score = self._get_score(c)
            if self._is_passed(score):
                try:
                    total_passed_credits += float(self._get_credits(c) or 0)
                except ValueError:
                    pass

        return {
            "count": len(courses),
            "passed_count": len(passed_names),
            "passed_credits": total_passed_credits,
            "passed_names": list(passed_names),
            "all_names": list(all_names),
            "source": str(self.csv_path) if self.csv_path.exists() else None,
        }