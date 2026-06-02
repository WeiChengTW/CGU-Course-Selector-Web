"""Course-Selector-Web 配置管理"""

from pathlib import Path

# 專案根目錄
BASE_DIR = Path(__file__).resolve().parent.parent

# 資料目錄
DATA_DIR = BASE_DIR / "data"

# 確保資料目錄存在
DATA_DIR.mkdir(parents=True, exist_ok=True)