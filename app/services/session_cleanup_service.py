"""Session 自動清理服務 - 定期清理過期的 session 目錄"""

import asyncio
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from app.config import get_logger
from app.services.session_service import SESSION_ROOT, SESSION_META_FILE

logger = get_logger(__name__)


async def cleanup_expired_sessions(max_age_hours: int = 4):
    """
    清理過期的 session 目錄

    Args:
        max_age_hours: Session 最大保留時間（小時），預設 4 小時（同 cookie max_age）
    """
    if not SESSION_ROOT.exists():
        logger.info("session_cleanup_skipped", reason="SESSION_ROOT不存在")
        return

    now = datetime.now()
    cutoff_time = now - timedelta(hours=max_age_hours)
    deleted_count = 0
    error_count = 0

    logger.info("session_cleanup_started", cutoff_time=cutoff_time.isoformat(), max_age_hours=max_age_hours)

    for session_dir in SESSION_ROOT.iterdir():
        if not session_dir.is_dir():
            continue

        try:
            meta_path = session_dir / SESSION_META_FILE
            if not meta_path.exists():
                # 沒有 meta 檔案，用目錄的修改時間判斷
                dir_mtime = datetime.fromtimestamp(session_dir.stat().st_mtime)
                if dir_mtime < cutoff_time:
                    logger.info("session_cleanup_deleting",
                               session_id=session_dir.name,
                               reason="無meta檔案且目錄過舊",
                               dir_mtime=dir_mtime.isoformat())
                    shutil.rmtree(session_dir)
                    deleted_count += 1
                continue

            # 讀取 meta 檔案檢查 created_at
            import json
            with meta_path.open("r", encoding="utf-8") as f:
                meta = json.load(f)

            created_at_str = meta.get("created_at")
            if not created_at_str:
                # meta 沒有 created_at，用檔案修改時間
                meta_mtime = datetime.fromtimestamp(meta_path.stat().st_mtime)
                if meta_mtime < cutoff_time:
                    logger.info("session_cleanup_deleting",
                               session_id=session_dir.name,
                               reason="meta無created_at且檔案過舊",
                               meta_mtime=meta_mtime.isoformat())
                    shutil.rmtree(session_dir)
                    deleted_count += 1
                continue

            # 解析 created_at
            created_at = datetime.fromisoformat(created_at_str)
            if created_at < cutoff_time:
                logger.info("session_cleanup_deleting",
                           session_id=session_dir.name,
                           created_at=created_at.isoformat(),
                           age_hours=round((now - created_at).total_seconds() / 3600, 2))
                shutil.rmtree(session_dir)
                deleted_count += 1

        except Exception as e:
            error_count += 1
            logger.error("session_cleanup_error",
                        session_id=session_dir.name,
                        error=str(e),
                        exc_info=True)

    logger.info("session_cleanup_completed",
               deleted_count=deleted_count,
               error_count=error_count)


async def session_cleanup_task():
    """背景任務 - 每小時執行一次 session 清理"""
    logger.info("session_cleanup_task_started")

    while True:
        try:
            await asyncio.sleep(3600)  # 每小時執行一次
            await cleanup_expired_sessions(max_age_hours=4)
        except asyncio.CancelledError:
            logger.info("session_cleanup_task_cancelled")
            break
        except Exception as e:
            logger.error("session_cleanup_task_error", error=str(e), exc_info=True)
            # 發生錯誤後繼續運行，避免背景任務停止
