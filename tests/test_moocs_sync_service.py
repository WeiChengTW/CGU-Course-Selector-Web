import unittest

from app.services.moocs_sync_service import parse_grade_rows


class MoocsSyncServiceTest(unittest.TestCase):
    def test_parse_grade_rows_extracts_course_credits_and_scores(self):
        text = """
課程名稱
學分數
修課成績
1142-物件導向軟體設計
3
1141-英文專修學習
1
81
1122-基礎英文(B)
2
S
"""

        rows = parse_grade_rows(text)

        self.assertEqual(
            rows,
            [
                {"學年學期": "1142", "課程名稱": "物件導向軟體設計", "學分數": "3", "修課成績": ""},
                {"學年學期": "1141", "課程名稱": "英文專修學習", "學分數": "1", "修課成績": "81"},
                {"學年學期": "1122", "課程名稱": "基礎英文(B)", "學分數": "2", "修課成績": "S"},
            ],
        )

    def test_parse_grade_rows_deduplicates_repeated_page_text(self):
        text = """
課程名稱
學分數
修課成績
1141-英文專修學習
1
81
課程名稱
學分數
修課成績
1141-英文專修學習
1
81
"""

        rows = parse_grade_rows(text)

        self.assertEqual(
            rows,
            [{"學年學期": "1141", "課程名稱": "英文專修學習", "學分數": "1", "修課成績": "81"}],
        )


if __name__ == "__main__":
    unittest.main()
