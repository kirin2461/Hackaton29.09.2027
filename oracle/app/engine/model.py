"""Доменная модель конкурсного набора (официальная схема §2.1 техприложения).

Типы объектов входного GeoJSON (properties.object_type, таблица 2.1):
  source                — источник теплоснабжения (Point)
  heat_network          — существующая тепловая сеть (LineString)
  heat_chamber          — существующая тепловая камера (Point)
  oks_future            — перспективный ОКС (Polygon / MultiPolygon)
  oks_connection_point  — точка подключения перспективного ОКС (Point)
  oks_existing          — существующий ОКС (Polygon / MultiPolygon)
  restriction           — пространственное ограничение (по типу, таблица 5.1)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from shapely.geometry import LineString, Point


@dataclass
class Source:
    """Источник теплоснабжения (корень цепочки upstream_object_id)."""

    object_id: str
    geom: Point


@dataclass
class Segment:
    """Участок существующей тепловой сети."""

    object_id: str
    geom: LineString
    diameter_mm: Optional[float] = None
    flow_tph: float = 0.0
    next_object_id: Optional[str] = None  # upstream_object_id — к источнику


@dataclass
class Chamber:
    """Тепловая камера (существующая).

    diameter_mm — входное значение: максимальный условный диаметр
    существующих участков, уже примыкающих к камере (§2.2).
    """

    object_id: str
    geom: Point
    diameter_mm: Optional[float] = None
    occupied_connections: int = 0   # запасной ввод (не из официальной схемы)
    next_object_id: Optional[str] = None  # upstream_object_id


@dataclass
class Building:
    """Перспективный ОКС."""

    object_id: str
    geom: object  # Polygon / MultiPolygon / Point
    flow_tph: float
    connection_point: Optional[Point] = None   # заполняется при загрузке
    connection_point_id: Optional[str] = None  # id точки подключения (§2.2: oks_id)

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
    """Пространственное ограничение (restriction, таблица 5.1).

    kind: forbidden | special_passage — правило обработки;
    restriction_type — исходный тип (road, oks_existing, ...);
    params — атрибуты входа + правило из справочника.
    """

    object_id: str
    geom: object  # Polygon / MultiPolygon / LineString / Point
    kind: str
    params: dict = field(default_factory=dict)
    restriction_type: Optional[str] = None


@dataclass
class ContestData:
    """Разобранный конкурсный набор в метрической СК."""

    segments: dict[str, Segment]
    chambers: dict[str, Chamber]
    buildings: dict[str, Building]
    constraints: list[ConstraintZone]
    crs_from: str          # исходная СК (EPSG:4326 по техприложению)
    crs_work: str          # рабочая метрическая СК
    bounds: tuple          # (minx, miny, maxx, maxy) в рабочей СК
    sources: dict[str, Source] = field(default_factory=dict)
    warnings: list = field(default_factory=list)
