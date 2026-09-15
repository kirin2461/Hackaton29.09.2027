"""Генератор синтетического конкурсного набора (Спринт 2, тест движка).

Район ~1.5 км под Москвой (EPSG:4326): линейная существующая сеть
«источник → камеры → участки», 5 перспективных ОКС (два кластеризуются),
ограничения обоих видов правил техприложения. Значения подобраны так,
чтобы сработали все механики: кластеризация, врезка по §8.2 (в камеру
≤10 м — B5; иначе новая камера на проекции), реконструкция, спецпроход,
предельная длина.
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
        # --- существующая сеть (цепочка к источнику: next_object_id) ---
        feat(line([[37.5000, 55.8700], [37.5030, 55.8700]]),
             {"object_type": "existing_segment", "object_id": "S0",
              "diameter_mm": 500, "flow_tph": 800, "next_object_id": None}),
        feat(point(37.5030, 55.8700),
             {"object_type": "chamber", "object_id": "C0",
              "occupied_connections": 1, "next_object_id": "S0"}),
        feat(line([[37.5030, 55.8700], [37.5060, 55.8700]]),
             {"object_type": "existing_segment", "object_id": "S1",
              "diameter_mm": 200, "flow_tph": 100, "next_object_id": "C0"}),
        feat(point(37.5060, 55.8700),
             {"object_type": "chamber", "object_id": "C1",
              "occupied_connections": 2, "next_object_id": "S1"}),
        feat(line([[37.5060, 55.8700], [37.5090, 55.8700]]),
             {"object_type": "existing_segment", "object_id": "S2",
              "diameter_mm": 150, "flow_tph": 60, "next_object_id": "C1"}),
        feat(point(37.5090, 55.8700),
             {"object_type": "chamber", "object_id": "C2",
              "occupied_connections": 1, "next_object_id": "S2"}),
        feat(line([[37.5090, 55.8700], [37.5120, 55.8700]]),
             {"object_type": "existing_segment", "object_id": "S3",
              "diameter_mm": 150, "flow_tph": 60, "next_object_id": "C2"}),

        # --- перспективные ОКС ---
        # B1 + B2 — кластер (точки подключения ~170 м друг от друга)
        feat(poly(37.5080, 55.8735, 0.0004, 0.0003),
             {"object_type": "prospective_building", "object_id": "B1", "flow_tph": 25}),
        feat(point(37.5080, 55.8728),
             {"object_type": "connection_point", "object_id": "CP1", "building_id": "B1"}),
        feat(poly(37.5095, 55.8740, 0.0004, 0.0003),
             {"object_type": "prospective_building", "object_id": "B2", "flow_tph": 30}),
        feat(point(37.5095, 55.8732),
             {"object_type": "connection_point", "object_id": "CP2", "building_id": "B2"}),
        # B3 — отдельно, южнее; на пути — спецпроход
        feat(poly(37.5140, 55.8690, 0.0004, 0.0003),
             {"object_type": "prospective_building", "object_id": "B3", "flow_tph": 45}),
        feat(point(37.5135, 55.8695),
             {"object_type": "connection_point", "object_id": "CP3", "building_id": "B3"}),
        # B4 — отдельно, западнее; большой расход → перегруз магистрали
        feat(poly(37.5020, 55.8740, 0.0004, 0.0003),
             {"object_type": "prospective_building", "object_id": "B4", "flow_tph": 90}),
        feat(point(37.5020, 55.8732),
             {"object_type": "connection_point", "object_id": "CP4", "building_id": "B4"}),
        # B5 — точка подключения в 7,8 м от камеры C1 (≤10 м, примыкания
        # свободны) → по §8.2 врезка в существующую камеру, без новой
        feat(poly(37.5060, 55.8708, 0.0004, 0.0003),
             {"object_type": "prospective_building", "object_id": "B5", "flow_tph": 20}),
        feat(point(37.5060, 55.87007),
             {"object_type": "connection_point", "object_id": "CP5", "building_id": "B5"}),

        # --- ограничения ---
        # запретная зона между сетью и кластером B1/B2 — объезд
        feat(poly(37.5088, 55.8715, 0.0006, 0.0004),
             {"object_type": "constraint", "object_id": "Z1", "constraint_type": "forbidden"}),
        # минимальное расстояние (охранная зона) у B4
        feat(point(37.5020, 55.8720),
             {"object_type": "constraint", "object_id": "Z2",
              "constraint_type": "min_distance", "min_distance_m": 20}),
        # спецпроход на пути к B3
        feat(poly(37.5125, 55.8697, 0.00025, 0.0006),
             {"object_type": "constraint", "object_id": "Z4", "constraint_type": "special_passage"}),
    ]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as fh:
        json.dump({"type": "FeatureCollection", "features": features}, fh, ensure_ascii=False)
    print(f"написано: {OUT} ({len(features)} объектов)")


if __name__ == "__main__":
    main()
