"""Потоковый загрузчик конкурсного GeoJSON (официальная схема §2.1).

Файл до 3 ГБ читается ijson'ом — объекты разбираются по одному,
в память не поднимаются целиком. СК формализованы техприложением:
вход — EPSG:4326 (валидируется, иное отклоняется), все расчёты —
в EPSG:32637 (переопределяется ENGINE_SOURCE_CRS / ENGINE_WORK_CRS).

Типы объектов — таблица 2.1 техприложения (source, heat_network,
heat_chamber, oks_future, oks_connection_point, oks_existing,
restriction); сохранены синонимы ранних внутренних наборов.
"""

from __future__ import annotations

import math
import os
import re
from pathlib import Path
from typing import Any, Optional

import ijson
from pyproj import Transformer
from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.ops import transform as shp_transform

from .model import Building, Chamber, ConstraintZone, ContestData, Segment, Source


class PipelineInputError(Exception):
    """Входной файл не соответствует конкурсной схеме."""


# Типы объектов: официальные (таблица 2.1) + синонимы ранних наборов
_OBJECT_TYPE_ALIASES = {
    "source": "source",
    "heat_source": "source",
    "heat_network": "existing_segment",
    "existing_segment": "existing_segment",
    "network_segment": "existing_segment",
    "existing_network": "existing_segment",
    "existing_network_segment": "existing_segment",
    "heat_chamber": "chamber",
    "chamber": "chamber",
    "thermal_chamber": "chamber",
    "oks_future": "prospective_building",
    "prospective_building": "prospective_building",
    "building": "prospective_building",
    "oks": "prospective_building",
    "oks_connection_point": "connection_point",
    "connection_point": "connection_point",
    "oks_existing": "oks_existing",
    "existing_building": "oks_existing",
    "restriction": "constraint",
    "constraint": "constraint",
    "spatial_constraint": "constraint",
}

# Синонимы типов ограничений → канонические restriction_type (таблица 5.1)
_RESTRICTION_TYPE_ALIASES = {
    "road": "road",
    "tram_tracks": "tram_tracks",
    "tram": "tram_tracks",
    "gas_pipeline": "gas_pipeline",
    "gas": "gas_pipeline",
    "power_cable": "power_cable",
    "cable": "power_cable",
    "heat_network": "heat_network",
    "park": "park",
    "social_area": "social_area",
    "prohibited_site": "prohibited_site",
    "water": "water",
    "oks_existing": "oks_existing",
    # ранние внутренние виды
    "forbidden": "prohibited_site",
    "no_build": "prohibited_site",
    "ban": "prohibited_site",
    "special_passage": "road",
    "special": "road",
    "min_distance": "oks_existing",
}

_EPSG_RE = re.compile(r"EPSG[^0-9]{0,4}(\d{4,5})", re.IGNORECASE)


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
    """Shapely-геометрия из GeoJSON (Point/LineString/Polygon/MultiPolygon)."""
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
    if gtype == "MultiPolygon":
        return MultiPolygon([Polygon(p[0], p[1:]) for p in coords])
    return None


def _geometry_problem(geom) -> Optional[str]:
    """Диагностика невалидной геометрии (протокол 16.09.2026 п.9).

    None — геометрия корректна; иначе — текст причины.
    """
    if geom is None:
        return "отсутствует или неподдерживаемый тип геометрии"
    if geom.is_empty:
        return "пустая геометрия"
    if not all(math.isfinite(v) for v in geom.bounds):
        return "неконечные координаты"
    if isinstance(geom, (Polygon, MultiPolygon)) and not geom.is_valid:
        return "невалидный полигон (самопересечение, OGC)"
    if isinstance(geom, LineString) and geom.length <= 0:
        return "нулевая длина линии"
    return None


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


def _resolve_constraint(oid: str, props: dict, geom, refdata,
                        warnings: list[str]) -> Optional[ConstraintZone]:
    """Свести restriction к виду правила (forbidden / special_passage).

    Тип ограничения — из restriction_type (таблица 5.1); правила — из
    справочника reference.yaml. Неизвестный тип — предупреждение и пропуск.
    """
    raw = str(_pick(props, "restriction_type", "constraint_type", "kind") or "").strip()
    rtype = _RESTRICTION_TYPE_ALIASES.get(raw, raw)
    rule = refdata.restriction_rule(rtype) if refdata else None
    if rule is None:
        warnings.append(
            f"{oid}: неизвестный тип ограничения '{raw}' — пропущен")
        return None
    kind = "forbidden" if rule.get("rule") == "forbidden" else "special_passage"
    return ConstraintZone(object_id=oid, geom=geom, kind=kind,
                          params=dict(props), restriction_type=rtype)


def load_contest_geojson(path: Path, refdata=None, max_scan_points: int = 50) -> ContestData:
    """Разобрать конкурсный GeoJSON в доменную модель (метрическая СК).

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

    segments: dict[str, Segment] = {}
    chambers: dict[str, Chamber] = {}
    buildings: dict[str, Building] = {}
    sources: dict[str, Source] = {}
    conn_points: dict[str, Point] = {}
    conn_owner: dict[str, str] = {}
    constraints: list[ConstraintZone] = []
    warnings: list[str] = []
    invalid_geom: list[str] = []   # п.9: диагностика невалидной геометрии
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
            if kind is None:
                continue  # неизвестный тип объекта — пропуск без диагностики
            oid = str(_pick(props, "object_id", "id", "uid")
                      or f"{kind}:{len(segments) + len(chambers) + len(buildings)}")
            geom = project(_build_geom(feat.get("geometry")))
            bad = _geometry_problem(geom)
            if bad:
                invalid_geom.append(f"{oid}: {bad}")
                continue
            _extend_bounds(geom)

            if kind == "source":
                sources[oid] = Source(
                    object_id=oid,
                    geom=geom if isinstance(geom, Point) else geom.centroid)
            elif kind == "existing_segment":
                if not isinstance(geom, LineString):
                    warnings.append(f"{oid}: сегмент сети не LineString — пропущен")
                    continue
                segments[oid] = Segment(
                    object_id=oid,
                    geom=geom,
                    diameter_mm=_as_float(_pick(props, "diameter", "diameter_mm", "dn_mm", "dn")),
                    flow_tph=_as_float(_pick(props, "flow_tph", "flow", "consumption_tph")) or 0.0,
                    next_object_id=_as_str(_pick(props, "upstream_object_id",
                                                 "next_object_id", "next_id", "next")),
                )
            elif kind == "chamber":
                chambers[oid] = Chamber(
                    object_id=oid,
                    geom=geom if isinstance(geom, Point) else geom.centroid,
                    diameter_mm=_as_float(_pick(props, "diameter", "diameter_mm", "dn_mm", "dn")),
                    occupied_connections=int(_as_float(
                        _pick(props, "occupied_connections", "occupied")) or 0),
                    next_object_id=_as_str(_pick(props, "upstream_object_id",
                                                 "next_object_id", "next_id", "next")),
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
                owner = _as_str(_pick(props, "oks_id", "building_id", "parent_id"))
                if owner:
                    conn_owner[oid] = owner
            elif kind == "oks_existing":
                # Существующий ОКС — запретная зона с отступом по Ду (§5.1)
                constraints.append(ConstraintZone(
                    object_id=oid, geom=geom, kind="forbidden",
                    params=dict(props), restriction_type="oks_existing"))
            elif kind == "constraint":
                zone = _resolve_constraint(oid, props, geom, refdata, warnings)
                if zone is not None:
                    constraints.append(zone)

    # Протокол 16.09.2026 п.9: невалидная геометрия — диагностическая ошибка
    if invalid_geom:
        shown = "; ".join(invalid_geom[:20])
        more = f"; и ещё {len(invalid_geom) - 20}" if len(invalid_geom) > 20 else ""
        raise PipelineInputError(
            f"невалидная геометрия ({len(invalid_geom)} объектов): {shown}{more}")

    # Привязка точек подключения к ОКС (§2.2: oks_id)
    for cp_id, pt in conn_points.items():
        owner = conn_owner.get(cp_id)
        if owner and owner in buildings:
            buildings[owner].connection_point = pt
            buildings[owner].connection_point_id = cp_id
        else:
            # Точка без владельца — ближайший ОКС
            best = min(buildings.values(), key=lambda b: b.anchor.distance(pt), default=None)
            if best is not None and best.anchor.distance(pt) < 200:
                best.connection_point = pt
                best.connection_point_id = cp_id

    if not segments and not chambers:
        raise PipelineInputError(
            "во входном файле не найдено объектов конкурсной схемы "
            "(heat_network / heat_chamber с properties.object_type)"
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
        sources=sources,
        warnings=warnings,
    )


def _as_float(v) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _as_str(v) -> Optional[str]:
    return str(v) if v is not None else None
