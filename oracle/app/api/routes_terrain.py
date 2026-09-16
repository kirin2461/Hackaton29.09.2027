"""Роуты рельефа / триангуляции (День 3) + лидарный рельеф (LAS/LAZ)."""

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field

from ..config import DATA_DIR
from ..deps import get_parser
from ..gis.parser import GISParser
from ..terrain import lidar
from ..terrain.triangulation import terrain_mesh, triangulate

router = APIRouter(prefix="/api/terrain", tags=["terrain"])


@router.get("/mesh")
def get_terrain_mesh(parser: GISParser = Depends(get_parser)):
    """Low-poly сетка демо-рельефа: плоские массивы vertices и faces.

    Размер участка подгоняется под охват загруженных геоданных,
    чтобы рельеф накрывал всю карту (у реальных слоёв OSM она
    не обязана быть 1000×1000 м).

    Фронтенд собирает из них THREE.BufferGeometry:
      geometry.setAttribute('position', Float32BufferAttribute(vertices, 3));
      geometry.setIndex(faces);
    """
    raw = parser._bounds()
    size = max(raw[2] - raw[0], raw[3] - raw[1]) if raw else None
    if size is None or size <= 0:
        size = None
    # Если загружен лидар — рельеф строится из реального облака точек.
    if lidar.active() and size:
        return lidar.mesh(size * 1.05)
    return terrain_mesh(size=size * 1.05) if size else terrain_mesh()


class PointsRequest(BaseModel):
    """Тело POST /api/terrain/triangulate — произвольное облако точек."""

    points: list[list[float]] = Field(
        ..., description="Список точек [[x, y, z], ...], минимум 3"
    )


@router.post("/triangulate")
def post_triangulate(req: PointsRequest):
    """Триангуляция Делоне для точек, присланных клиентом.

    Нужна на будущее: когда появится реальная ЦМР или пользовательские
    отметки высот, фронтенд сможет триангулировать их на лету.
    """
    return triangulate(req.points)


# --- Лидар: загрузка LAS/LAZ, демо, облако точек ------------------

LIDAR_DEMO = DATA_DIR / "lidar_demo.laz"
LIDAR_DEMO_NPZ = DATA_DIR / "lidar_demo.npz"


def _map_size(parser: GISParser) -> float:
    raw = parser._bounds()
    if not raw:
        return 1000.0
    size = max(raw[2] - raw[0], raw[3] - raw[1])
    return (size * 1.05) if size > 0 else 1000.0


@router.get("/lidar/status")
def lidar_status():
    """Активен ли лидарный рельеф и статистика облака."""
    return lidar.status()


@router.post("/lidar/demo")
def lidar_demo():
    """Загружает встроенный демо-лидар (Autzen Stadium, USGS 3DEP)."""
    # Предобработанный npz — мгновенно; иначе честная обработка LAZ.
    if LIDAR_DEMO_NPZ.exists():
        return lidar.load_precomputed(LIDAR_DEMO_NPZ)
    if not LIDAR_DEMO.exists():
        raise HTTPException(404, "Демо-файл lidar_demo не найден")
    try:
        return lidar.load(LIDAR_DEMO, source_name="Autzen Stadium (USGS 3DEP)")
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.post("/lidar/upload")
async def lidar_upload(file: UploadFile):
    """Загрузка своего LAS/LAZ (например, облёт площадки дроном).

    Файл должен быть классифицированным (нужны ground-точки,
    класс 2) — иначе ЦМР построить не из чего.
    """
    name = (file.filename or "cloud.laz").lower()
    if not name.endswith((".las", ".laz")):
        raise HTTPException(400, "Нужен файл .las или .laz")
    suffix = ".laz" if name.endswith(".laz") else ".las"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name
    try:
        return lidar.load(tmp_path, source_name=file.filename)
    except ValueError as e:
        raise HTTPException(422, str(e))
    finally:
        Path(tmp_path).unlink(missing_ok=True)


@router.post("/lidar/clear")
def lidar_clear():
    """Возврат к процедурному демо-рельефу."""
    lidar.clear()
    return {"ok": True, "active": False}


@router.get("/lidar/cloud.bin")
def lidar_cloud(parser: GISParser = Depends(get_parser)):
    """Облако точек для WebGL: uint32 N + float32 xyz×N + uint8 rgb×N."""
    if not lidar.active():
        raise HTTPException(404, "Лидар не загружен")
    return Response(content=lidar.cloud_bytes(_map_size(parser)),
                    media_type="application/octet-stream")
