"""Экспорт результата в выходной GeoJSON (§2.10 ТЗ, Спринт 2).

Единый FeatureCollection в EPSG:4326. Каждый объект — feature с
properties.object_type и обязательными атрибутами:

  new_segment            — новый участок (диаметр, расход, длина, метод, стоимость)
  new_chamber            — новая камера (врезка в трубу / разветвление)
  technical_node         — техузел предельной длины диаметра
  tapping                — точка врезки (в существующую камеру)
  reconstruction_segment — участок существующей сети под реконструкцию
  reconstruction_chamber — камера под реконструкцию
  unconnected            — ОКС без маршрута (§2.9: частичный результат)
"""

from __future__ import annotations

import json
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import LineString, mapping
from shapely.ops import transform as shp_transform


def write_result(path: Path, data, new_segments, new_chambers, tech_nodes,
                 taps, recon, unconnected, summary: dict) -> None:
    back = Transformer.from_crs(data.crs_work, "EPSG:4326", always_xy=True).transform

    def to4326(geom):
        return shp_transform(back, geom)

    def feature(geom, props):
        return {
            "type": "Feature",
            "geometry": mapping(to4326(geom)),
            "properties": props,
        }

    features = []

    for seg in new_segments:
        features.append(feature(LineString(seg.coords), {
            "object_type": "new_segment",
            "object_id": seg.object_id,
            "role": seg.role,
            "method": seg.method,
            "diameter_mm": seg.diameter_mm,
            "flow_tph": round(seg.flow_tph, 3),
            "length_m": round(seg.length_m, 1),
            "cost_rub": round(seg.cost_rub, 2),
            "warnings": seg.warnings,
        }))

    for ch in new_chambers:
        features.append(feature(ch["point"], {
            "object_type": "new_chamber",
            "object_id": ch["object_id"],
            "kind": ch["kind"],
            "on_segment_id": ch.get("segment_id"),
            "cost_rub": round(ch["cost_rub"], 2),
        }))

    for node in tech_nodes:
        features.append(feature(node.point, {
            "object_type": "technical_node",
            "object_id": node.object_id,
            "reason": node.reason,
        }))

    for tap in taps:
        if tap.kind == "existing_chamber":
            features.append(feature(tap.point, {
                "object_type": "tapping",
                "chamber_id": tap.chamber_id,
                "flow_tph": round(tap.flow_tph, 3),
                "cost_rub": round(tap.tap_cost_rub, 2),
            }))

    for rs in recon.segments:
        seg = data.segments[rs.object_id]
        features.append(feature(seg.geom, {
            "object_type": "reconstruction_segment",
            "object_id": rs.object_id,
            "existing_diameter_mm": rs.existing_dn,
            "required_diameter_mm": rs.required_dn,
            "existing_flow_tph": rs.existing_flow_tph,
            "added_flow_tph": round(rs.added_flow_tph, 3),
            "length_m": rs.length_m,
            "cost_rub": round(rs.cost_rub, 2),
        }))

    for rc in recon.chambers:
        ch = data.chambers[rc.object_id]
        features.append(feature(ch.geom, {
            "object_type": "reconstruction_chamber",
            "object_id": rc.object_id,
            "reason": rc.reason,
            "cost_rub": round(rc.cost_rub, 2),
        }))

    for u in unconnected:
        features.append(feature(u["point"], {
            "object_type": "unconnected",
            "building_id": u["building_id"],
            "reason": u["reason"],
        }))

    collection = {
        "type": "FeatureCollection",
        "metadata": summary,
        "features": features,
    }

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(collection, fh, ensure_ascii=False)
