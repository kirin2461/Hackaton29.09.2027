"""Конфигурация backend-приложения (День 1).

Все настройки собраны в одном месте, чтобы не размазывать
«магические числа» по коду. Значения можно переопределить
переменными окружения.
"""

import os
from pathlib import Path

# Корень пакета backend/app — от него считаем относительные пути.
BASE_DIR = Path(__file__).resolve().parent

# Папка с демо-геоданными (GeoJSON-слои: здания, дороги, теплосети).
DATA_DIR = Path(os.getenv("GIS_DATA_DIR", BASE_DIR / "data"))

# Исходная система координат демо-данных (WGS84, градусы).
SOURCE_CRS = os.getenv("GIS_SOURCE_CRS", "EPSG:4326")

# Рабочая система координат — локальная метрическая (метры).
# UTM zone 37N подходит для Москвы и центра европейской части РФ;
# для другого города поменяйте на свою зону UTM.
TARGET_CRS = os.getenv("GIS_TARGET_CRS", "EPSG:32637")

# CORS: адреса фронтенда, которым разрешено ходить в API.
# 5173 — dev-сервер Vite, 8000 — на случай отдачи сборки самим FastAPI.
CORS_ORIGINS = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8000",
).split(",")

# Параметры сетки рельефа для триангуляции (День 3):
# размер квадратного участка в метрах и число узлов сетки по одной оси.
TERRAIN_SIZE_M = float(os.getenv("TERRAIN_SIZE_M", "1000"))
TERRAIN_GRID = int(os.getenv("TERRAIN_GRID", "40"))

# Высота одного этажа в метрах — для «выдавливания» зданий (День 4).
FLOOR_HEIGHT_M = float(os.getenv("FLOOR_HEIGHT_M", "3.0"))
