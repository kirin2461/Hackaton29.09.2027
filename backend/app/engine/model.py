"""Доменная модель конкурсного набора (Спринт 2).

Типы объектов входного GeoJSON (properties.object_type):
  existing_segment      — участок существующей сети (LineString)
  chamber               — тепловая камера (Point)
  prospective_building  — перспективный ОКС (Polygon|Point)
  connection_point      — точка подключения ОКС (Point)
  constraint            — пространственное ограничение (Polygon|LineString)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from shapely.geometry import LineString, Point, Polygon


@dataclass
class Segment:
    """Участок существующей тепловой сети."""

    object_id: str
    geom: LineString
    diameter_mm: Optional[float] = None
    flow_tph: float = 0.0
    next_object_id: Optional[str] = None


@dataclass
class Chamber:
    """Тепловая камера (существующая)."""

    object_id: str
    geom: Point
    occupied_connections: int = 0
    next_object_id: Optional[str] = None  # следующий объект к источнику


@dataclass
class Building:
    """Перспективный ОКС."""

    object_id: str
    geom: object  # Polygon или Point
    flow_tph: float
    connection_point: Optional[Point] = None  # заполняется при загрузке

    @property
    def anchor(self) -> Point:
        """Точка привязки: точка подключения, иначе центроид."""
        if self.connection_point is not None:
            return self.connection_point
        if isinstance(self.geom, Point):
            return self.geom
        return self.geom.centroid


@dataclass
class ConstraintZone:
    """Пространственное ограничение.

    kind: forbidden | min_distance | special_passage   # по техприложению — два вида правил
    params: min_distance_m, min_angle_deg, method и др. — из properties.
    """

    object_id: str
    geom: object  # Polygon или LineString
    kind: str
    params: dict = field(default_factory=dict)


@dataclass
class ContestData:
    """Разобранный конкурсный набор в метрической СК."""

    segments: dict[str, Segment]
    chambers: dict[str, Chamber]
    buildings: dict[str, Building]
    constraints: list[ConstraintZone]
    crs_from: str          # исходная СК (как правило EPSG:4326)
    crs_work: str          # рабочая метрическая СК (UTM)
    bounds: tuple          # (minx, miny, maxx, maxy) в рабочей СК
    warnings: list = field(default_factory=list)
