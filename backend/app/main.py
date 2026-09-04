"""Точка входа FastAPI-приложения (День 1).

Запуск из папки backend/:
    uvicorn app.main:app --reload --port 8000

Swagger-документация API: http://localhost:8000/docs
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes_map import router as map_router
from .api.routes_project import router as project_router
from .api.routes_terrain import router as terrain_router
from .config import CORS_ORIGINS

app = FastAPI(
    title="Hackaton29 — ГИС + 3D теплосети",
    description="Backend хакатон-проекта: ГИС-парсер, триангуляция рельефа, расчёт подключения зданий к теплосетям.",
    version="0.1.0",
)

# CORS нужен, чтобы React dev-сервер (порт 5173) мог ходить в API (порт 8000).
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(map_router)
app.include_router(terrain_router)
app.include_router(project_router)


@app.get("/api/health")
def health():
    """Проверка живости сервиса — фронтенд дёргает её при старте."""
    return {"status": "ok"}
