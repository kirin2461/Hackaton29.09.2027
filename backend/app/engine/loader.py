"""Потоковый загрузчик конкурсного GeoJSON (Спринт 2).

Файл до 3 ГБ читается ijson'ом — объекты разбираются по одному,
в память не поднимаются целиком. СК формализованы техприложением:
вход — EPSG:4326 (валидируется, иное отклоняется), все расчёты —
в EPSG:32637 (явная проекция pyproj; переопределяется переменными
ENGINE_SOURCE_CRS / ENGINE_WORK_CRS).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

import ijson
from pyproj import Transformer
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import transform as shp_transform

from .model import Building, Chamber, ConstraintZone, ContestData, Segment


class PipelineInputError(Exception):
    """Входной файл не соответствует конкурсной схеме."""


# Синонимы типов объектов (техприложение может назвать их иначе)
_OBJECT_TYPE_ALIASES = {
    "existing_segment": "existing_segment",
    "network_segment": "existing_segment",
    "existing_network": "existing_segment",
    "existing_network_segment": "existing_segment",
    "heat_chamber": "chamber",
    "chamber": "chamber",
    "thermal_chamber": "chamber",
    "prospective_building": "prospective_building",
    "building": "prospective_building",
    "oks": "prospective_building",
    "connection_point": "connection_point",
    "constraint": "constraint",
    "restriction": "constraint",
    "spatial_constraint": "constraint",
}

# Синонимы видов ограничений
_CONSTRAINT_KIND_ALIASES = {
    "forbidden": "forbidden",
    "no_build": "forbidden",
    "ban": "forbidden",
    "min_distance": "min_distance",
    "distance": "min_distance",
    "special_passage": "special_passage",
    "special": "special_passage",
}


def _pick(props: dict, *names: str) -> Any:
    """Первое непустое значение из списка возможных имён атрибута."""
    for name in names:
        if name in props and props[name] is not None:
            return props[name]
    return None


def _to_float_coords(coords):
    """Рекурсивно приводит координаты к float (ijson отдаёт Decimal)."""
    if isinstance(coords, (list, tuple)):
        return [_to_float_coords(c) for c in coords]
    return float(coords)


def _build_geom(geom: dict):
    """Shapely-геометрия из GeoJSON-геометрии (Point/LineString/Polygon)."""
    if not geom:
        return None
    gtype = geom.get("type")
    coords = _to_float_coords(geom.get("coordinates"))
    if gtype == "Point":
        return Point(coords)
    if gtype == "LineString":
        return LineString(coords)
    if gtype == "Polygon":
        shell, *holes = coords
        return Polygon(shell, holes)
    return None


import re

_EPSG_RE = re.compile(r"EPSG[^0-9]{0,4}(\d{4,5})", re.IGNORECASE)


def _epsg_code(text: str) -> Optional[int]:
    """Код EPSG из строки вида 'EPSG:4326' или URN 'urn:ogc:def:crs:EPSG::4326'."""
    m = _EPSG_RE.search(text or "")
    return int(m.group(1)) if m else None


def _declared_crs(path: Path) -> Optional[str]:
    """Верхнеуровневый член 'crs' GeoJSON (если задан в файле)."""
    with path.open("rb") as fh:
        for prefix, event, value in ijson.parse(fh):
            if prefix == "crs.properties.name" and event == "string":
                return value
            if prefix == "features" and event == "start_array":
                return None
    return None


def load_contest_geojson(path: Path, max_scan_points: int = 50) -> ContestData:
    """Разобрать конкурсный GeoJSON в доменную модель (EPSG:32637).

    Однопроходный потоковый разбор. Перед разбором валидируется СК
    входа: по техприложению это EPSG:4326; если файл объявляет другую
    CRS — вход отклоняется.
    """
    path = Path(path)

    crs_from = os.getenv("ENGINE_SOURCE_CRS", "EPSG:4326")
    declared = _declared_crs(path)
    if declared:
        want, got = _epsg_code(crs_from), _epsg_code(declared)
        if want is None or got != want:
            raise PipelineInputError(
                f"входной файл в CRS '{declared}', ожидается {crs_from} "
                "(техприложение: вход строго в EPSG:4326)"
            )
    crs_work = os.getenv("ENGINE_WORK_CRS", "EPSG:32637")
    fwd = Transformer.from_crs(crs_from, crs_work, always_xy=True).transform
    project = lambda g: shp_transform(fwd, g) if g is not None else None  # noqa: E731

    # --- потоковый разбор ---
    segments: dict[str, Segment] = {}
    chambers: dict[str, Chamber] = {}
    buildings: dict[str, Building] = {}
    conn_points: dict[str, Point] = {}
    conn_owner: dict[str, str] = {}
    constraints: list[ConstraintZone] = []
    warnings: list[str] = []
    bounds = [float("inf"), float("inf"), float("-inf"), float("-inf")]

    def _extend_bounds(g) -> None:
        if g is None:
            return
        mnx, mny, mxx, mxy = g.bounds
        bounds[0] = min(bounds[0], mnx)
        bounds[1] = min(bounds[1], mny)
        bounds[2] = max(bounds[2], mxx)
        bounds[3] = max(bounds[3], mxy)

    with path.open("rb") as fh:
        for feat in ijson.items(fh, "features.item"):
            props = feat.get("properties") or {}
            raw_type = str(_pick(props, "object_type", "type", "layer") or "").strip()
            kind = _OBJECT_TYPE_ALIASES.get(raw_type)
            geom = project(_build_geom(feat.get("geometry")))
            if geom is None or kind is None:
                continue
            _extend_bounds(geom)
            oid = str(_pick(props, "object_id", "id", "uid") or f"{kind}:{len(segments) + len(chambers) + len(buildings)}")

            if kind == "existing_segment":
                if not isinstance(geom, LineString):
                    warnings.append(f"{oid}: сегмент сети не LineString — пропущен")
                    continue
                segments[oid] = Segment(
                    object_id=oid,
                    geom=geom,
                    diameter_mm=_as_float(_pick(props, "diameter_mm", "diameter", "dn_mm", "dn")),
                    flow_tph=_as_float(_pick(props, "flow_tph", "flow", "consumption_tph")) or 0.0,
                    next_object_id=_as_str(_pick(props, "next_object_id", "next_id", "next")),
                )
            elif kind == "chamber":
                chambers[oid] = Chamber(
                    object_id=oid,
                    geom=geom if isinstance(geom, Point) else geom.centroid,
                    occupied_connections=int(_as_float(_pick(props, "occupied_connections", "occupied")) or 0),
                    next_object_id=_as_str(_pick(props, "next_object_id", "next_id", "next")),
                )
            elif kind == "prospective_building":
                buildings[oid] = Building(
                    object_id=oid,
                    geom=geom,
                    flow_tph=_as_float(_pick(props, "flow_tph", "flow", "consumption_tph")) or 0.0,
                )
            elif kind == "connection_point":
                pt = geom if isinstance(geom, Point) else geom.centroid
                conn_points[oid] = pt
                owner = _as_str(_pick(props, "building_id", "oks_id", "parent_id"))
                if owner:
                    conn_owner[oid] = owner
            elif kind == "constraint":
                raw_kind = str(_pick(props, "constraint_type", "kind") or "").strip()
                ckind = _CONSTRAINT_KIND_ALIASES.get(raw_kind)
                if ckind is None:
                    warnings.append(f"{oid}: неизвестный тип ограничения '{raw_kind}' — пропущен")
                    continue
                constraints.append(ConstraintZone(object_id=oid, geom=geom, kind=ckind, params=props))

    # Привязка точек подключения к ОКС
    for cp_id, pt in conn_points.items():
        owner = conn_owner.get(cp_id)
        if owner and owner in buildings:
            buildings[owner].connection_point = pt
        else:
            # Точка без владельца — ближайший ОКС
            best = min(buildings.values(), key=lambda b: b.anchor.distance(pt), default=None)
            if best is not None and best.anchor.distance(pt) < 200:
                best.connection_point = pt

    if not segments and not chambers:
        raise PipelineInputError(
            "во входном файле не найдено объектов конкурсной схемы "
            "(existing_segment / chamber с properties.object_type)"
        )
    if not buildings:
        warnings.append("перспективные ОКС не найдены — результат пуст")

    if bounds[0] == float("inf"):
        raise PipelineInputError("входной файл не содержит геометрий")

    return ContestData(
        segments=segments,
        chambers=chambers,
        buildings=buildings,
        constraints=constraints,
        crs_from=crs_from,
        crs_work=crs_work,
        bounds=tuple(bounds),
        warnings=warnings,
    )


def _as_float(v) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _as_str(v) -> Optional[str]:
    return str(v) if v is not None else None
