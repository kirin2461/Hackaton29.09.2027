"""Роуты рельефа / триангуляции (День 3)."""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..terrain.triangulation import terrain_mesh, triangulate

router = APIRouter(prefix="/api/terrain", tags=["terrain"])


@router.get("/mesh")
def get_terrain_mesh():
    """Low-poly сетка демо-рельефа: плоские массивы vertices и faces.

    Фронтенд собирает из них THREE.BufferGeometry:
      geometry.setAttribute('position', Float32BufferAttribute(vertices, 3));
      geometry.setIndex(faces);
    """
    return terrain_mesh()


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
