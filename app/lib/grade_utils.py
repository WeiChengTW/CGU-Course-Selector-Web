"""成績判斷工具模組 - 統一的成績狀態判斷邏輯與 GPA 計算"""

# 字母成績 → 級點對照表
GRADE_POINT_MAP = {
    'A+': 4.3, 'A': 4.0, 'A-': 3.7,
    'B+': 3.3, 'B': 3.0, 'B-': 2.7,
    'C+': 2.3, 'C': 2.0, 'C-': 1.7,
    'D+': 1.3, 'D': 1.0, 'D-': 0.7,
    'F': 0.0,
    # 特殊標記不列入 GPA
    'P': None, 'S': None, 'I': None, '通過': None, '及格': None,
}


def grade_to_point(grade: str):
    """
    將成績轉換為級點（GPA point）

    Args:
        grade: 成績字串（字母或數字）

    Returns:
        float 級點，或 None 表示不列入 GPA 計算
    """
    if not grade:
        return None

    grade = grade.strip().upper()

    # 字母成績
    if grade in GRADE_POINT_MAP:
        return GRADE_POINT_MAP[grade]

    # 數字成績 → 級點
    try:
        num = float(grade)
        if num < 60:
            return 0.0
        # 90+ → A+ (4.3), 85-89 → A (4.0), 80-84 → A- (3.7)...
        if num >= 90:
            return 4.3
        elif num >= 85:
            return 4.0
        elif num >= 80:
            return 3.7
        elif num >= 77:
            return 3.3
        elif num >= 73:
            return 3.0
        elif num >= 70:
            return 2.7
        elif num >= 67:
            return 2.3
        elif num >= 63:
            return 2.0
        elif num >= 60:
            return 1.7
        return 0.0
    except ValueError:
        return None


def calculate_gpa(courses: list[dict], score_field: str = '修課成績', credit_field: str = '學分') -> dict:
    """
    計算 GPA

    Args:
        courses: 課程列表（每門課含成績和學分欄位）
        score_field: 成績欄位名
        credit_field: 學分欄位名

    Returns:
        dict: { "gpa": float, "total_credits": int, "total_points": float }
    """
    total_points = 0.0
    total_credits = 0.0

    for course in courses:
        score = course.get(score_field, '')
        credit = course.get(credit_field, 0)

        point = grade_to_point(score)
        if point is None:
            continue  # 不列入 GPA

        try:
            credit_num = float(credit)
        except (ValueError, TypeError):
            continue

        if credit_num <= 0:
            continue

        total_points += point * credit_num
        total_credits += credit_num

    gpa = total_points / total_credits if total_credits > 0 else 0.0
    return {
        'gpa': round(gpa, 2),
        'total_credits': round(total_credits, 1),
        'total_points': round(total_points, 2),
    }


def is_passed(score: str) -> bool:
    """
    判斷成績是否通過（60分以上或特殊通過標記）

    Args:
        score: 成績字串

    Returns:
        True 如果通過，False 如果未通過或進行中
    """
    if not score:
        return False

    score = score.strip().upper()

    # S = 停休, I = 進行中
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


def is_in_progress(score: str) -> bool:
    """
    判斷課程是否進行中（尚未有成績）

    Args:
        score: 成績字串

    Returns:
        True 如果進行中，False 如果已有結果
    """
    if not score:
        return True

    score = score.strip().upper()
    return score == 'I'


def get_status(score: str) -> str:
    """
    取得成績狀態

    Args:
        score: 成績字串

    Returns:
        "passed" | "failed" | "in_progress"
    """
    if is_in_progress(score):
        return "in_progress"
    elif is_passed(score):
        return "passed"
    else:
        return "failed"
