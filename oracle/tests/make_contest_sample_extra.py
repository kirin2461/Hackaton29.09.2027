"""Второй синтетический набор (актуальная схема §1) — «особые случаи».

  - ЧИСЛОВЫЕ id точек подключения (101, 102, ...) — контроль сохранения
    типа идентификаторов в end_node_id и unconnected_oks_ids (§7.2);
  - заполненная камера KF (4 примыкания): точка Q5 в 8 м от неё —
    камера отклоняется, строится НОВАЯ камера на ближайшем участке (§2.4);
  - tram_tracks (полигон, K=1,75) и tram как MultiLineString — контроль
    разбора MultiLineString (§1.1);
  - power_cable (K=1,15, ±2 м), water / social_area / prohibited_site
    (запреты, 1,0 м);
  - Q6 внутри social_area — неподключение (штраф 100 млн + 500 тыс. × 150).
"""

import json
from pathlib import Path

OUT = Path(__file__).parent / "data" / "contest_sample_extra.geojson"


def feat(geom, props):
    return {"type": "Feature", "geometry": geom, "properties": props}


def line(coords):
    return {"type": "LineString", "coordinates": coords}


def point(x, y):
    return {"type": "Point", "coordinates": [x, y]}


def poly(cx, cy, dx, dy):
    return {"type": "Polygon", "coordinates": [[
        [cx - dx, cy - dy], [cx + dx, cy - dy],
        [cx + dx, cy + dy], [cx - dx, cy + dy],
        [cx - dx, cy - dy],
    ]]}


def main():
    features = [
        # --- источник и существующая сеть (L-образная + стабы на KF) ---
        feat(point(37.6180, 55.8600),
             {"object_type": "source", "id": "SRCX"}),
        feat(line([[37.6180, 55.8600], [37.6200, 55.8600]]),
             {"object_type": "heat_network", "id": "W0", "diameter": 300}),
        # KF — ЗАПОЛНЕНА: W0 (запад) + S0 (юг) + NW (северо-запад) + N0 (восток)
        feat(point(37.6200, 55.8600),
             {"object_type": "heat_chamber", "id": "KF"}),
        feat(line([[37.6200, 55.8580], [37.6200, 55.8600]]),
             {"object_type": "heat_network", "id": "S0", "diameter": 100}),
        feat(line([[37.6190, 55.8610], [37.6200, 55.8600]]),
             {"object_type": "heat_network", "id": "NW", "diameter": 100}),
        feat(line([[37.6200, 55.8600], [37.6230, 55.8600]]),
             {"object_type": "heat_network", "id": "N0", "diameter": 300}),
        feat(point(37.6230, 55.8600),
             {"object_type": "heat_chamber", "id": "K0"}),
        feat(line([[37.6230, 55.8600], [37.6230, 55.8630]]),
             {"object_type": "heat_network", "id": "N1", "diameter": 200}),
        feat(point(37.6230, 55.8630),
             {"object_type": "heat_chamber", "id": "K1"}),

        # --- точки подключения (ЧИСЛОВЫЕ id) и их полигоны ОКС ---
        # 101 — на пути трамвай (полигон, K=1,75)
        feat(point(37.6245, 55.8635),
             {"object_type": "oks_connection_point", "id": 101, "flow_tph": 25}),
        feat(poly(37.6245, 55.8635, 0.00035, 0.00025),
             {"object_type": "restriction", "id": "OX1", "restriction_type": "oks"}),
        # 102 — на пути силовой кабель (K=1,15) и трамвай-MultiLineString
        feat(point(37.6215, 55.8645),
             {"object_type": "oks_connection_point", "id": 102, "flow_tph": 5}),
        feat(poly(37.6215, 55.8645, 0.00035, 0.00025),
             {"object_type": "restriction", "id": "OX2", "restriction_type": "oks"}),
        # 103 — западнее; рядом водный объект (объезд)
        feat(point(37.6180, 55.8620),
             {"object_type": "oks_connection_point", "id": 103, "flow_tph": 60}),
        feat(poly(37.6180, 55.8620, 0.00035, 0.00025),
             {"object_type": "restriction", "id": "OX3", "restriction_type": "oks"}),
        # 104 — восточнее, между prohibited_site и водой
        feat(point(37.6260, 55.8595),
             {"object_type": "oks_connection_point", "id": 104, "flow_tph": 12}),
        feat(poly(37.6260, 55.8595, 0.0003, 0.0002),
             {"object_type": "restriction", "id": "OX4", "restriction_type": "oks"}),
        # 105 — в 8 м от ЗАПОЛНЕННОЙ камеры KF → новая камера на стабе S0
        feat(point(37.6200, 55.85993),
             {"object_type": "oks_connection_point", "id": 105, "flow_tph": 6}),
        # 106 — внутри social_area → неподключение (штраф 175 млн ₽)
        feat(point(37.6240, 55.8615),
             {"object_type": "oks_connection_point", "id": 106, "flow_tph": 150}),

        # --- ограничения (таблица 2) ---
        # трамвай-полигон поперёк пути к 101 (K=1,75)
        feat(poly(37.6240, 55.8630, 0.0002, 0.0005),
             {"object_type": "restriction", "id": "T1", "restriction_type": "tram_tracks"}),
        # трамвай-MultiLineString (проверка разбора §1.1) далеко на севере
        feat({"type": "MultiLineString", "coordinates": [
            [[37.6210, 55.8660], [37.6220, 55.8660]],
            [[37.6230, 55.8660], [37.6240, 55.8660]]]},
             {"object_type": "restriction", "id": "T2", "restriction_type": "tram_tracks"}),
        # силовой кабель поперёк пути к 102 (K=1,15)
        feat(line([[37.6205, 55.8638], [37.6225, 55.8638]]),
             {"object_type": "restriction", "id": "E1", "restriction_type": "power_cable"}),
        # водный объект западнее (объезд к 103)
        feat(poly(37.6195, 55.8615, 0.0004, 0.0003),
             {"object_type": "restriction", "id": "W1", "restriction_type": "water"}),
        # social_area — накрывает точку 106
        feat(poly(37.6240, 55.8615, 0.0003, 0.0003),
             {"object_type": "restriction", "id": "SA1", "restriction_type": "social_area"}),
        # prohibited_site восточнее (рядом с 104)
        feat(poly(37.6270, 55.8600, 0.0003, 0.0003),
             {"object_type": "restriction", "id": "PB1", "restriction_type": "prohibited_site"}),
    ]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as fh:
        json.dump({
            "type": "FeatureCollection",
            "crs": {"type": "name",
                    "properties": {"name": "urn:ogc:def:crs:EPSG::4326"}},
            "features": features,
        }, fh, ensure_ascii=False)
    print(f"написано: {OUT} ({len(features)} объектов)")


if __name__ == "__main__":
    main()
