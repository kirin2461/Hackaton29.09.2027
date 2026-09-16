"""Роут «Точка посадки» (День 5).

Фронтенд присылает:
  - Точку Б — полигон нового перспективного здания и его этажность;
  - Точку А — id выбранной существующей теплосети.

Бэкенд находит ближайшую точку врезки на выбранной теплосети
до контура нового здания (shapely: nearest_points), считает длину
трассировки по прямой и возвращает геометрию соединения — фронтенд
рисует её пунктирной линией в 3D-сцене.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from shapely.geometry import LineString, Polygon
from shapely.ops import nearest_points

from ..deps import get_parser
from ..gis.parser import LAYER_HEAT, GISParser

router = APIRouter(prefix="/api/project", tags=["project"])


class NewBuilding(BaseModel):
    """Точка Б — новое перспективное здание."""

    polygon: list[list[float]] = Field(
        ..., description="Кольцо контура [[x, y], ...] в метрах, минимум 3 точки"
    )
    floors: int = Field(5, ge=1, le=100, description="Этажность здания")
    name: str = Field("Новое здание", description="Название проекта")


class ConnectionRequest(BaseModel):
    """Запрос на расчёт подключения: Точка Б + Точка А."""

    building: NewBuilding
    network_id: str = Field(..., description="id линии теплосети (Точка А)")


@router.post("/connect")
def connect(req: ConnectionRequest, parser: GISParser = Depends(get_parser)):
    """Рассчитывает врезку нового здания в выбранную теплосеть."""
    if len(req.building.polygon) < 3:
        raise HTTPException(400, "Контуру здания нужно минимум 3 точки")

    # Ищем выбранную теплосеть (Точка А) среди объектов слоя.
    features = parser.layer_to_features(LAYER_HEAT)
    target = next((f for f in features if f["id"] == req.network_id), None)
    if target is None:
        raise HTTPException(404, f"Теплосеть '{req.network_id}' не найдена")

    # Координаты слоя на фронтенде нормализованы (отсчёт от левого
    # нижнего угла охвата карты, см. GISParser.to_response), поэтому
    # линию теплосети приводим к той же системе перед расчётом.
    raw_bounds = parser._bounds()
    ox, oy = (raw_bounds[0], raw_bounds[1]) if raw_bounds else (0.0, 0.0)
    network = LineString([(x - ox, y - oy) for x, y in target["coordinates"]])
    building = Polygon(req.building.polygon)
    if not building.is_valid:
        raise HTTPException(400, "Некорректный контур здания")

    # Ближайшие точки между контуром здания и линией теплосети.
    p_building, p_network = nearest_points(building, network)
    length_m = float(p_building.distance(p_network))

    # Грубая оценка тепловой нагрузки: 60 Вт/м² по площади застройки
    # (усреднённый показатель для жилых зданий, только для демо).
    heat_load_kw = round(float(building.area) * req.building.floors * 0.06, 1)

    return {
        "building": {
            "name": req.building.name,
            "floors": req.building.floors,
            "area_m2": round(float(building.area), 1),
            "heat_load_kw": heat_load_kw,
        },
        "network_id": req.network_id,
        "connection": {
            "from_point": [round(p_building.x, 2), round(p_building.y, 2)],
            "to_point": [round(p_network.x, 2), round(p_network.y, 2)],
            "length_m": round(length_m, 1),
        },
    }


# ---------- День 14-15: сохранение проекта ----------

import json
import uuid
from datetime import datetime, timezone

from ..config import PROJECTS_DIR
from ..deps import get_normalized_layers
from ..routing.estimate import validate_path


class SaveRequest(BaseModel):
    """Сохранение трассы: здание, сеть и финальная полилиния."""

    building: NewBuilding
    network_id: str
    path: list[list[float]] = Field(..., description="Точки трассы [[x, y], ...]")
    variant: str = Field("custom", description="Ключ варианта или 'custom' после правок")


def _safe_polygon(coords):
    """Строит валидный полигон из координат фичи слоя или None."""
    try:
        p = Polygon(coords)
    except (TypeError, ValueError):
        return None
    return p if p.is_valid else None


@router.post("/save")
def save_project(req: SaveRequest, layers: dict = Depends(get_normalized_layers)):
    """Сохраняет проект трассировки в JSON на сервере.

    День 14: если трасса пересекает здание (пользователь затянул
    трубу gizmo'м под дом), сохранение блокируется ошибкой 409 —
    фронтенд при этом ещё и гасит кнопку.
    """
    check = validate_path(req.path, layers)
    if check["collision"]:
        raise HTTPException(
            409,
            f"Трасса пересекает здания: {', '.join(check['collision_buildings'])}. "
            "Исправьте трассу перед сохранением.",
        )

    # Новое здание не должно пересекаться с существующей застройкой.
    placed = Polygon(req.building.polygon)
    overlap = [
        f["id"]
        for f in layers.get("buildings", [])
        if (p := _safe_polygon(f.get("coordinates"))) is not None
        and placed.intersects(p)
    ]
    if overlap:
        raise HTTPException(
            409,
            f"Здание пересекается с существующими: {', '.join(overlap)}. "
            "Переместите его на свободное место.",
        )

    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    project_id = uuid.uuid4().hex[:8]
    payload = {
        "id": project_id,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "building": req.building.model_dump(),
        "network_id": req.network_id,
        "variant": req.variant,
        "path": req.path,
        "estimate": check,
    }
    (PROJECTS_DIR / f"{project_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return {"saved": True, "project_id": project_id, "estimate": check}
