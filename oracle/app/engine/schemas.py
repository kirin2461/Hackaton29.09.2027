"""Pydantic-схемы конкурсного входного GeoJSON (§2.1–2.2 техприложения).

Справочные схемы входных атрибутов (таблица 2.2). Все справочники
(пропускная способность, предельные длины, тарифы, правила ограничений)
живут во внешнем reference.yaml — никаких констант набора в коде (§2.14).
"""

from typing import Optional

from pydantic import BaseModel


class SourceProps(BaseModel):
    """Источник теплоснабжения (source)."""

    id: str

    class Config:
        extra = "allow"


class HeatNetworkProps(BaseModel):
    """Участок существующей тепловой сети (heat_network)."""

    id: str
    diameter: Optional[float] = None           # условный диаметр, мм
    flow_tph: Optional[float] = None           # расчётный расход, т/ч
    upstream_object_id: Optional[str] = None   # следующий объект к источнику

    class Config:
        extra = "allow"


class HeatChamberProps(BaseModel):
    """Существующая тепловая камера (heat_chamber).

    diameter — максимальный условный диаметр существующих участков,
    уже примыкающих к камере (§2.2). Лимит примыканий — 4 (§8.2).
    """

    id: str
    diameter: Optional[float] = None
    upstream_object_id: Optional[str] = None

    class Config:
        extra = "allow"


class OksFutureProps(BaseModel):
    """Перспективный ОКС (oks_future)."""

    id: str
    flow_tph: float                # расход для расчёта новой сети, т/ч
    heat_load: Optional[float] = None  # справочная тепловая нагрузка, Гкал/ч

    class Config:
        extra = "allow"


class OksConnectionPointProps(BaseModel):
    """Точка подключения перспективного ОКС (oks_connection_point)."""

    id: str
    oks_id: Optional[str] = None   # ID объекта oks_future

    class Config:
        extra = "allow"


class RestrictionProps(BaseModel):
    """Пространственное ограничение (restriction, таблица 5.1)."""

    id: str
    restriction_type: str          # road / tram_tracks / gas_pipeline / ...

    class Config:
        extra = "allow"
