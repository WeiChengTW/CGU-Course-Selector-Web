"""Course-Selector-Web - 長庚大學選課視覺化系統"""

from fastapi import FastAPI

from app.config import BASE_DIR

app = FastAPI(
    title="長庚大學選課系統",
    description="畢業學分計算與選課建議視覺化系統",
    version="1.0.0",
)

# 掛載路由
from app.routes import courses, catalog, graduation, recommend, home, auth

app.include_router(home.router)
app.include_router(auth.router, tags=["auth"])
app.include_router(courses.router, prefix="/courses", tags=["courses"])
app.include_router(catalog.router, prefix="/catalog", tags=["catalog"])
app.include_router(graduation.router, prefix="/graduation", tags=["graduation"])
app.include_router(recommend.router, prefix="/recommend", tags=["recommend"])