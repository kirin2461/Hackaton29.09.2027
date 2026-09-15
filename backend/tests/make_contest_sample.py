"""Генератор синтетического конкурсного набора (официальная схема §2.1).

Район ~1.5 км (EPSG:4326): линейная существующая сеть
«SRC → S0 → C0 → S1 → C1 → S2 → C2 → S3», 5 перспективных ОКС
(B1+B2 кластеризуются), ограничения по таблице 5.1. Значения подобраны
так, чтобы сработали все механики техприложения:

  §7   — реконструкция: S1 (100+35+45+20=200 → Ду250), S2 (60+35+45=140
         и 60+45=105 → Ду200, частичная геометрия), S3 (60+45=105 → Ду200);
  §8.2 — B5: точка подключения в 7,8 м от камеры C1 → врезка в существующую
         камеру (5 млн ₽); реконструкция камер C1 (200→250, 5 млн) и
         C2 (150→200, 3 млн);
  §5.1 — park (запрет, объезд), road (спецпроход K=1,60), газопровод-
         линия (спецпроход K=1,25, границы ±2 м от точки пересечения);
  oks_existing — существующий ОКС (отступ 5/7/9 м по Ду новой сети).
"""

import json
from pathlib import Path

OUT = Path(__file__).parent / "data" / "contest_sample.geojson"


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
        # --- источник и существующая сеть (upstream_object_id) ---
        feat(point(37.5000, 55.8700),
             {"object_type": "source", "id": "SRC"}),
        feat(line([[37.5000, 55.8700], [37.5030, 55.8700]]),
             {"object_type": "heat_network", "id": "S0",
              "diameter": 500, "flow_tph": 800, "upstream_object_id": "SRC"}),
        feat(point(37.5030, 55.8700),
             {"object_type": "heat_chamber", "id": "C0",
              "diameter": 500, "upstream_object_id": "S0"}),
        feat(line([[37.5030, 55.8700], [37.5060, 55.8700]]),
             {"object_type": "heat_network", "id": "S1",
              "diameter": 200, "flow_tph": 100, "upstream_object_id": "C0"}),
        feat(point(37.5060, 55.8700),
             {"object_type": "heat_chamber", "id": "C1",
              "diameter": 200, "upstream_object_id": "S1"}),
        feat(line([[37.5060, 55.8700], [37.5090, 55.8700]]),
             {"object_type": "heat_network", "id": "S2",
              "diameter": 150, "flow_tph": 60, "upstream_object_id": "C1"}),
        feat(point(37.5090, 55.8700),
             {"object_type": "heat_chamber", "id": "C2",
              "diameter": 150, "upstream_object_id": "S2"}),
        feat(line([[37.5090, 55.8700], [37.5120, 55.8700]]),
             {"object_type": "heat_network", "id": "S3",
              "diameter": 150, "flow_tph": 60, "upstream_object_id": "C2"}),

        # --- перспективные ОКС (§2.1: oks_future + oks_connection_point) ---
        # B1 + B2 — кластер (точки подключения ~100 м друг от друга)
        feat(poly(37.5080, 55.8735, 0.0004, 0.0003),
             {"object_type": "oks_future", "id": "B1", "flow_tph": 15, "heat_load": 8.1}),
        feat(point(37.5080, 55.8728),
             {"object_type": "oks_connection_point", "id": "CP1", "oks_id": "B1"}),
        # B2 — MultiPolygon (проверка поддержки §2.1)
        {"type": "Feature",
         "geometry": {"type": "MultiPolygon", "coordinates": [[[
             [37.5091, 55.8737], [37.5099, 55.8737],
             [37.5099, 55.8743], [37.5091, 55.8743],
             [37.5091, 55.8737]]]]},
         "properties": {"object_type": "oks_future", "id": "B2",
                        "flow_tph": 20, "heat_load": 10.8}},
        feat(point(37.5095, 55.8732),
             {"object_type": "oks_connection_point", "id": "CP2", "oks_id": "B2"}),
        # B3 — отдельно, восточнее; на пути — дорога (спецпроход K=1,60)
        feat(poly(37.5140, 55.8690, 0.0004, 0.0003),
             {"object_type": "oks_future", "id": "B3", "flow_tph": 45, "heat_load": 24.3}),
        feat(point(37.5135, 55.8695),
             {"object_type": "oks_connection_point", "id": "CP3", "oks_id": "B3"}),
        # B4 — отдельно, западнее; на пути — газопровод (спецпроход K=1,25)
        feat(poly(37.5020, 55.8740, 0.0004, 0.0003),
             {"object_type": "oks_future", "id": "B4", "flow_tph": 90, "heat_load": 48.6}),
        feat(point(37.5020, 55.8732),
             {"object_type": "oks_connection_point", "id": "CP4", "oks_id": "B4"}),
        # B5 — точка подключения в 7,8 м от камеры C1 (≤10 м, примыкания
        # свободны) → по §8.2 врезка в существующую камеру, без новой
        feat(poly(37.5060, 55.8708, 0.0004, 0.0003),
             {"object_type": "oks_future", "id": "B5", "flow_tph": 20, "heat_load": 10.8}),
        feat(point(37.5060, 55.87007),
             {"object_type": "oks_connection_point", "id": "CP5", "oks_id": "B5"}),

        # --- существующий ОКС (запрет, отступ 5/7/9 м по Ду новой сети) ---
        feat(poly(37.5040, 55.8725, 0.0003, 0.0003),
             {"object_type": "oks_existing", "id": "OX1"}),

        # --- пространственные ограничения (restriction, таблица 5.1) ---
        # парк между сетью и кластером B1/B2 — объезд
        feat(poly(37.5088, 55.8715, 0.0006, 0.0004),
             {"object_type": "restriction", "id": "Z1", "restriction_type": "park"}),
        # газопровод-линия поперёк пути к B4 (спецпроход ±2 м, K=1,25)
        feat(line([[37.5010, 55.8720], [37.5030, 55.8720]]),
             {"object_type": "restriction", "id": "Z2", "restriction_type": "gas_pipeline"}),
        # дорога-полоса поперёк пути к B3 (спецпроход +3 м за границы, K=1,60)
        feat(poly(37.5125, 55.8697, 0.00025, 0.0006),
             {"object_type": "restriction", "id": "Z4", "restriction_type": "road"}),
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
