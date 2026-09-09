"""Роуты рельефа / триангуляции (День 3)."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..deps import get_parser
from ..gis.parser import GISParser
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
        return terrain_mesh()
    return terrain_mesh(size=size * 1.05)  # небольшой запас по краям


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
