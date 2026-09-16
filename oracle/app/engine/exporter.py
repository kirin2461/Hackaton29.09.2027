"""Экспорт результата в выходной GeoJSON — строго по разделу 10.

Один файл FeatureCollection (EPSG:4326) содержит объекты ВСЕХ вариантов
(variant_id у каждого объекта). Ровно семь типов объектов, у каждого —
только свой набор атрибутов (таблицы 10.1–10.7), без посторонних полей
и без metadata:

  heat_network                 — новый линейный участок;
  tie_in                       — точка врезки в существующую сеть;
  heat_network_reconstruction  — реконструируемая часть существующего участка;
  heat_chamber                 — новая тепловая камера;
  heat_chamber_reconstruction  — реконструкция существующей камеры;
  technical_node               — технический узел;
  variant_summary              — сводная запись варианта (geometry: null).
"""

from __future__ import annotations

import json
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import LineString, mapping
from shapely.ops import transform as shp_transform

from .reconstruction import Reconstruction


def write_result(path: Path, data, variants: list, summary: dict) -> None:
    back = Transformer.from_crs(data.crs_work, "EPSG:4326", always_xy=True).transform

    def to4326(geom):
        return shp_transform(back, geom)

    def feature(geom, props):
        return {
            "type": "Feature",
            "geometry": mapping(to4326(geom)) if geom is not None else None,
            "properties": props,
        }

    def chamber_existing_dn(ch) -> float:
        if ch.diameter_mm:
            return ch.diameter_mm
        adj = [s.diameter_mm or 0.0 for s in data.segments.values()
               if s.next_object_id == ch.object_id]
        return max(adj) if adj else 0.0

    features = []

    for variant in variants:
        vid = str(variant.get("rank", 0))

        # --- §10.1: новые линейные участки ---
        for seg in variant["new_segments"]:
            features.append(feature(LineString(seg.coords), {
                "id": seg.object_id,
                "object_type": "heat_network",
                "variant_id": vid,
                "start_node_id": seg.start_node_id,
                "end_node_id": seg.end_node_id,
                "flow_tph": round(seg.flow_tph, 3),
                "diameter": int(seg.diameter_mm),
                "length": round(seg.length_m, 1),
                "laying_method": seg.method,   # base | special
                "depth_start": seg.depth_start,  # null в 2D-задаче (§8.1)
                "depth_end": seg.depth_end,
                "cost": round(seg.cost_rub, 2),
            }))

        # --- §10.2: точки врезки ---
        for tap in variant["taps"]:
            if tap.kind == "existing_chamber":
                ch = data.chambers[tap.chamber_id]
                existing_id = tap.chamber_id
                existing_type = "heat_chamber"
                existing_dn = chamber_existing_dn(ch)
            else:
                seg0 = data.segments[tap.segment_id]
                existing_id = tap.segment_id
                existing_type = "heat_network"
                existing_dn = seg0.diameter_mm or 0.0
            features.append(feature(tap.point, {
                "id": tap.node_id,
                "object_type": "tie_in",
                "variant_id": vid,
                "existing_object_id": existing_id,
                "existing_object_type": existing_type,
                "existing_diameter": int(existing_dn),
                "required_diameter": int(tap.required_dn),
                "cost": round(tap.tap_cost_rub, 2),
            }))

        # --- §10.3: реконструкция линейных участков ---
        recon: Reconstruction = variant["recon"]
        for rs in recon.segments:
            features.append(feature(rs.geom, {
                "id": rs.object_id,
                "object_type": "heat_network_reconstruction",
                "variant_id": vid,
                "existing_object_id": rs.existing_object_id,
                "existing_flow_tph": rs.existing_flow,
                "added_flow_tph": rs.added_flow,
                "calculated_flow_tph": rs.calculated_flow,
                "existing_diameter": int(rs.existing_dn),
                "required_diameter": int(rs.required_dn),
                "length": rs.length_m,
                "cost": rs.cost_rub,
            }))

        # --- §10.4: новые камеры ---
        for ch in variant["new_chambers"]:
            features.append(feature(ch["point"], {
                "id": ch["object_id"],
                "object_type": "heat_chamber",
                "variant_id": vid,
                "diameter": int(ch["diameter_mm"]),
                "cost": round(ch["cost_rub"], 2),
            }))

        # --- §10.5: реконструкция существующих камер ---
        for rc in recon.chambers:
            features.append(feature(data.chambers[rc.existing_object_id].geom, {
                "id": rc.object_id,
                "object_type": "heat_chamber_reconstruction",
                "variant_id": vid,
                "existing_object_id": rc.existing_object_id,
                "existing_diameter": int(rc.existing_dn),
                "required_diameter": int(rc.required_dn),
                "cost": rc.cost_rub,
            }))

        # --- §10.6: технические узлы ---
        for node in variant["tech_nodes"]:
            features.append(feature(node.point, {
                "id": node.object_id,
                "object_type": "technical_node",
                "variant_id": vid,
            }))

        # --- §10.7: сводная запись варианта (geometry: null) ---
        costs = variant["costs"]
        lengths = variant["lengths"]
        features.append(feature(None, {
            "id": f"summary-{vid}",
            "object_type": "variant_summary",
            "variant_id": vid,
            "rank": int(variant.get("rank", 0)),
            "construction_cost": costs["construction_cost"],
            "chamber_construction_cost": costs["chamber_construction_cost"],
            "tie_in_cost": costs["tie_in_cost"],
            "reconstruction_cost": costs["reconstruction_cost"],
            "chamber_reconstruction_cost": costs["chamber_reconstruction_cost"],
            "unconnected_penalty": costs["unconnected_penalty"],
            "calculated_cost": costs["calculated_cost"],
            "new_network_length": lengths["new_network_length"],
            "reconstruction_length": lengths["reconstruction_length"],
            "length": lengths["length"],
            "score": variant.get("score"),
            "unconnected_oks_ids": list(variant["unconnected_ids"]),
        }))

    collection = {
        "type": "FeatureCollection",
        "features": features,
    }

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(collection, fh, ensure_ascii=False)
