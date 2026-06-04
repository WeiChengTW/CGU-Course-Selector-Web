"""Course-Selector-Web - 長庚大學選課視覺化系統"""

import asyncio
from typing import Optional

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi_csrf_protect import CsrfProtect
from fastapi_csrf_protect.exceptions import CsrfProtectError
from pydantic_settings import BaseSettings
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config import BASE_DIR, configure_logging, get_logger

# 配置日誌
configure_logging()
logger = get_logger(__name__)


class CsrfSettings(BaseSettings):
    """CSRF 保護設定"""
    secret_key: str = "change-this-to-a-random-secret-key-in-production"
    cookie_samesite: str = "lax"
    cookie_secure: bool = False  # Production 環境應設為 True (需要 HTTPS)
    cookie_httponly: bool = True
    cookie_domain: Optional[str] = None


@CsrfProtect.load_config
def get_csrf_config():
    return CsrfSettings()


app = FastAPI(
    title="長庚大學選課系統",
    description="畢業學分計算與選課建議視覺化系統",
    version="1.0.0",
)

# CORS middleware (如果需要的話)
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"],
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )


@app.exception_handler(CsrfProtectError)
async def csrf_protect_exception_handler(request: Request, exc: CsrfProtectError):
    """CSRF 驗證失敗處理"""
    logger.warning("csrf_validation_failed", path=request.url.path, error=str(exc))
    return JSONResponse(
        status_code=403,
        content={"detail": "CSRF token 驗證失敗，請重新載入頁面後再試。"}
    )


@app.on_event("startup")
async def startup_event():
    """應用啟動事件 - 啟動背景任務"""
    logger.info("application_starting")

    # 啟動 session 清理背景任務
    from app.services.session_cleanup_service import session_cleanup_task
    asyncio.create_task(session_cleanup_task())
    logger.info("session_cleanup_task_scheduled")


@app.on_event("shutdown")
async def shutdown_event():
    """應用關閉事件"""
    logger.info("application_shutting_down")


# 掛載路由
from app.routes import auth, catalog, courses, graduation, home, recommend

app.include_router(home.router)
app.include_router(auth.router, tags=["auth"])
app.include_router(courses.router, prefix="/courses", tags=["courses"])
app.include_router(catalog.router, prefix="/catalog", tags=["catalog"])
app.include_router(graduation.router, prefix="/graduation", tags=["graduation"])
app.include_router(recommend.router, prefix="/recommend", tags=["recommend"])

# Static files (favicon, etc.)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.get("/health", tags=["health"])
async def health_check():
    """健康檢查端點"""
    from datetime import datetime
    from app.config import BASE_DIR
    sessions_dir = BASE_DIR / "data" / "sessions"
    records_dir = BASE_DIR / "data" / "records"
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "sessions_dir_exists": sessions_dir.exists(),
        "records_dir_exists": records_dir.exists(),
    }