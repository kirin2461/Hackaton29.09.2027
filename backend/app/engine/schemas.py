"""Pydantic-схемы конкурсного входного GeoJSON (техприложение к ТЗ).

Спринт 1 — каркас: зафиксированы типы объектов и ключевые атрибуты.
Все справочники (пропускная способность диаметров, предельные длины,
тарифы, правила ограничений) со Спринта 2 живут во внешних конфигах —
никаких констант конкурсного набора в коде (§2.14 ТЗ).
"""

from typing import Optional

from pydantic import BaseModel


class ExistingSegmentProps(BaseModel):
    """Участок существующей тепловой сети."""

    object_id: str
    diameter_mm: Optional[float] = None   # условный диаметр, мм
    flow_tph: Optional[float] = None      # расчётный расход, т/ч
    next_object_id: Optional[str] = None  # ID следующего объекта к источнику

    class Config:
        extra = "allow"


class HeatChamberProps(BaseModel):
    """Тепловая камера (лимит — 4 примыкания, из них ≤3 в новых направлениях)."""

    object_id: str
    occupied_connections: int = 0

    class Config:
        extra = "allow"


class ProspectiveBuildingProps(BaseModel):
    """Перспективный ОКС (объект капитального строительства)."""

    object_id: str
    flow_tph: float  # расход, т/ч

    class Config:
        extra = "allow"


class ConnectionPointProps(BaseModel):
    """Точка подключения ОКС."""

    object_id: str
    building_id: Optional[str] = None

    class Config:
        extra = "allow"


class ConstraintProps(BaseModel):
    """Пространственное ограничение: запрет / мин. расстояние /
    пересечение с условиями / спецпроход отдельным участком."""

    constraint_type: str

    class Config:
        extra = "allow"
