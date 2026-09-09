"""Роуты трассировки (Дни 6–10).

POST /api/route/compute — главный эндпоинт спринта 2:
фронтенд присылает Точку Б (контур нового здания) и Точку А
(id теплосети), бэкенд строит весовой граф карты, запускает A*
и возвращает три варианта трассы:
  - «Кратчайший»   — без штрафов, чистая геометрия;
  - «Экономичный»  — баланс длины, дорог и поворотов
                     (веса можно крутить бегунками в UI);
  - «В обход дорог» — дороги практически запрещены.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from shapely.geometry import Polygon

from ..deps import get_normalized_layers, get_parser, get_planner
from ..gis.parser import LAYER_HEAT, GISParser
from ..routing.estimate import validate_path
from ..routing.netstats import impact as network_impact
from ..routing.netstats import reliability as network_reliability
from ..routing.sitescan import scan_sites
from ..routing.planner import (
    DEFAULT_ROAD_MULTIPLIER,
    DEFAULT_TURN_PENALTY,
    RoutePlanner,
)

router = APIRouter(prefix="/api/route", tags=["route"])


class RouteBuilding(BaseModel):
    """Точка Б — новое перспективное здание."""

    polygon: list[list[float]] = Field(
        ..., description="Кольцо контура [[x, y], ...] в метрах, минимум 3 точки"
    )
    floors: int = Field(5, ge=1, le=100)
    name: str = Field("Новое здание")


class RouteRequest(BaseModel):
    building: RouteBuilding
    network_id: str = Field(..., description="id линии теплосети (Точка А)")
    # Бегунки UI: штраф за поворот (усл. м за 45°) и множитель дороги.
    turn_penalty: float = Field(DEFAULT_TURN_PENALTY, ge=0, le=50)
    road_multiplier: float = Field(DEFAULT_ROAD_MULTIPLIER, ge=1, le=50)


@router.post("/compute")
def compute_route(req: RouteRequest,
                  parser: GISParser = Depends(get_parser),
                  planner: RoutePlanner = Depends(get_planner),
                  layers: dict = Depends(get_normalized_layers)):
    """Считает три варианта трассы A* от теплосети до здания."""
    if len(req.building.polygon) < 3:
        raise HTTPException(400, "Контуру здания нужно минимум 3 точки")

    # Точка А — выбранная теплосеть (координаты нормализуем так же,
    # как в /api/map/layers: минус левый нижний угол охвата карты).
    features = parser.layer_to_features(LAYER_HEAT)
    target = next((f for f in features if f["id"] == req.network_id), None)
    if target is None:
        raise HTTPException(404, f"Теплосеть '{req.network_id}' не найдена")

    raw_bounds = parser._bounds()
    ox, oy = (raw_bounds[0], raw_bounds[1]) if raw_bounds else (0.0, 0.0)
    network_coords = [(x - ox, y - oy) for x, y in target["coordinates"]]

    try:
        result = planner.plan(
            network_coords,
            req.building.polygon,
            turn_penalty=req.turn_penalty,
            road_multiplier=req.road_multiplier,
        )
    except ValueError as e:
        raise HTTPException(422, str(e))

    # Справочная информация о здании (как в /api/project/connect).
    building = Polygon(req.building.polygon)
    result["building"] = {
        "name": req.building.name,
        "floors": req.building.floors,
        "area_m2": round(float(building.area), 1),
        "heat_load_kw": round(float(building.area) * req.building.floors * 0.06, 1),
    }
    result["network_id"] = req.network_id

    # Δ-импакт каждого варианта на живучесть сети (энтропия,
    # кольцевание, число Фидлера) — помогает выбрать не только
    # самую дешёвую, но и самую «безболезненную» для сети врезку.
    heat_lines = [f["coordinates"] for f in layers.get(LAYER_HEAT, [])]
    # Отказоустойчивость базовой сети (N-1 + Монте-Карло) — считаем
    # один раз, сравнение «до/после» фронт делает по ветке-варианту.
    result["reliability"] = {
        "before": network_reliability(heat_lines),
    }
    for v in result.get("variants", []):
        v["network_impact"] = network_impact(heat_lines, v["path"])

    # Проверка размещения: новое здание не должно пересекаться
    # со существующей застройкой. Трасса всё равно считается,
    # но фронтенд покажет предупреждение.
    placement = {"collision": False, "buildings": []}
    for feat in layers.get("buildings", []):
        try:
            other = Polygon(feat["coordinates"])
        except (TypeError, ValueError):
            continue
        if other.is_valid and building.intersects(other):
            placement["collision"] = True
            placement["buildings"].append(feat["id"])
    result["placement"] = placement
    return result


class ValidateRequest(BaseModel):
    """Тело POST /api/route/validate — полилиния трассы (Дни 12–14).

    Присылается после A* и после каждого перетаскивания узла трубы
    gizmo'м — бэкенд мгновенно возвращает коллизии и смету.
    """

    path: list[list[float]] = Field(
        ..., description="Точки трассы [[x, y], ...], минимум 2"
    )


@router.post("/validate")
def validate_route(req: ValidateRequest,
                   layers: dict = Depends(get_normalized_layers)):
    """Валидация трассы: коллизии, переходы под дорогами, смета
    и Δ-импакт ветки на живучесть теплосети (пересчитывается при
    каждом перетаскивании узла gizmo'м)."""
    try:
        result = validate_path(req.path, layers)
    except ValueError as e:
        raise HTTPException(422, str(e))
    heat_lines = [f["coordinates"] for f in layers.get(LAYER_HEAT, [])]
    result["network"] = network_impact(heat_lines, req.path)
    # Живучесть «до/после» врезки: точный N-1 и Монте-Карло
    # (каждое ребро отказывает с p=0.05, 300 сценариев, seed=2027).
    result["reliability"] = {
        "before": network_reliability(heat_lines),
        "after": network_reliability(heat_lines, req.path),
    }
    return result


class ScanRequest(BaseModel):
    """Тело POST /api/route/scan — обратная задача.

    Вместо «есть здание — проведи трубу» сканируем свободные
    участки квартала и ранжируем их по стоимости присоединения.
    """

    network_id: str | None = Field(
        None, description="id теплосети (по умолчанию — первая)")
    building_size: float = Field(40.0, ge=10, le=120,
                                 description="Сторона квадратной площадки, м")
    floors: int = Field(9, ge=1, le=100)
    step: float = Field(80.0, ge=30, le=300,
                        description="Шаг сетки сканирования, м")
    top: int = Field(5, ge=1, le=20)


@router.post("/scan")
def scan_route(req: ScanRequest,
               parser: GISParser = Depends(get_parser),
               planner: RoutePlanner = Depends(get_planner),
               layers: dict = Depends(get_normalized_layers)):
    """Ищет топ-N площадок под новое здание по цене присоединения."""
    heat_feats = layers.get(LAYER_HEAT, [])
    if not heat_feats:
        raise HTTPException(422, "В квартале нет теплосети для подключения")
    target = (next((f for f in heat_feats if f["id"] == req.network_id), None)
              if req.network_id else heat_feats[0])
    if target is None:
        raise HTTPException(404, f"Теплосеть '{req.network_id}' не найдена")

    raw_bounds = parser._bounds()
    ox, oy = (raw_bounds[0], raw_bounds[1]) if raw_bounds else (0.0, 0.0)
    w = (raw_bounds[2] - ox) if raw_bounds else 0.0
    h = (raw_bounds[3] - oy) if raw_bounds else 0.0

    result = scan_sites(layers, [0.0, 0.0, w, h], planner,
                        target["coordinates"],
                        size=req.building_size, floors=req.floors,
                        step=req.step, top=req.top)
    result["network_id"] = target["id"]
    # Живучесть базовой сети — чтобы фронт показал «до» рядом с Δ.
    heat_lines = [f["coordinates"] for f in heat_feats]
    result["reliability_before"] = network_reliability(heat_lines)
    return result
