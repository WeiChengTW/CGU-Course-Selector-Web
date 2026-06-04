"""Course-Selector-Web 配置管理"""

import sys
from pathlib import Path

import structlog
from dotenv import load_dotenv

# 專案根目錄
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# 資料目錄
DATA_DIR = BASE_DIR / "data"

# 確保資料目錄存在
DATA_DIR.mkdir(parents=True, exist_ok=True)


# Logging configuration
def configure_logging():
    """配置 structlog 結構化日誌"""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso", utc=False),
            structlog.dev.ConsoleRenderer(colors=True),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(20),  # INFO level
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """獲取結構化日誌器"""
    return structlog.get_logger(name)