"""Дополнительный синтетический набор для репетиции (§2.14, Спринт 4).

Другой район (~7 км восточнее, центр Москвы), ДРУГАЯ топология:
кольцевая существующая сеть (а не линейная), 5 ОКС:
  - E1, E2, E3 — цепочка из трёх ОКС вдоль одной улицы (кластер);
  - E4 — крупный ОКС (120 т/ч) → реконструкция двух участков кольца;
  - E5 — ОКС ВНУТРИ запретной зоны → должен уйти в unconnected (§2.9).
Проверка универсальности: никаких констант этого набора в коде нет.
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
        # --- кольцевая существующая сеть: R1→R2→R3→R4→(к источнику R0) ---
        feat(line([[37.6100, 55.7600], [37.6140, 55.7600]]),
             {"object_type": "existing_segment", "object_id": "R0",
              "diameter_mm": 600, "flow_tph": 1100, "next_object_id": None}),
        feat(point(37.6140, 55.7600),
             {"object_type": "chamber", "object_id": "RC0",
              "occupied_connections": 2, "next_object_id": "R0"}),
        feat(line([[37.6140, 55.7600], [37.6180, 55.7600]]),
             {"object_type": "existing_segment", "object_id": "R1",
              "diameter_mm": 300, "flow_tph": 250, "next_object_id": "RC0"}),
        feat(point(37.6180, 55.7600),
             {"object_type": "chamber", "object_id": "RC1",
              "occupied_connections": 2, "next_object_id": "R1"}),
        feat(line([[37.6180, 55.7600], [37.6180, 55.7640]]),
             {"object_type": "existing_segment", "object_id": "R2",
              "diameter_mm": 250, "flow_tph": 180, "next_object_id": "RC1"}),
        feat(point(37.6180, 55.7640),
             {"object_type": "chamber", "object_id": "RC2",
              "occupied_connections": 2, "next_object_id": "R2"}),
        feat(line([[37.6180, 55.7640], [37.6140, 55.7640]]),
             {"object_type": "existing_segment", "object_id": "R3",
              "diameter_mm": 200, "flow_tph": 120, "next_object_id": "RC2"}),
        feat(point(37.6140, 55.7640),
             {"object_type": "chamber", "object_id": "RC3",
              "occupied_connections": 1, "next_object_id": "R3"}),
        # обратная ветвь кольца (для топологии; в цепочку к источнику не входит)
        feat(line([[37.6140, 55.7640], [37.6140, 55.7600]]),
             {"object_type": "existing_segment", "object_id": "R4",
              "diameter_mm": 200, "flow_tph": 120, "next_object_id": "RC3"}),

        # --- перспективные ОКС ---
        # E1–E3 — цепочка вдоль улицы севернее кольца (кластер, радиус 300 м)
        feat(poly(37.6145, 55.7670, 0.0004, 0.0003),
             {"object_type": "prospective_building", "object_id": "E1", "flow_tph": 20}),
        feat(point(37.6145, 55.7662),
             {"object_type": "connection_point", "object_id": "ECP1", "building_id": "E1"}),
        feat(poly(37.6158, 55.7672, 0.0004, 0.0003),
             {"object_type": "prospective_building", "object_id": "E2", "flow_tph": 25}),
        feat(point(37.6158, 55.7664),
             {"object_type": "connection_point", "object_id": "ECP2", "building_id": "E2"}),
        feat(poly(37.6171, 55.7670, 0.0004, 0.0003),
             {"object_type": "prospective_building", "object_id": "E3", "flow_tph": 15}),
        feat(point(37.6171, 55.7662),
             {"object_type": "connection_point", "object_id": "ECP3", "building_id": "E3"}),
        # E4 — крупный ОКС южнее: 120 т/ч → R1 (300 мм, 250+120=370 > 310)
        # и R2 (250 мм, 180+120=300 > 210) уходят в реконструкцию
        feat(poly(37.6160, 55.7565, 0.0004, 0.0003),
             {"object_type": "prospective_building", "object_id": "E4", "flow_tph": 120}),
        feat(point(37.6160, 55.7573),
             {"object_type": "connection_point", "object_id": "ECP4", "building_id": "E4"}),
        # E5 — ВНУТРИ запретной зоны → unconnected
        feat(poly(37.6120, 55.7620, 0.0003, 0.0003),
             {"object_type": "prospective_building", "object_id": "E5", "flow_tph": 10}),
        feat(point(37.6120, 55.7620),
             {"object_type": "connection_point", "object_id": "ECP5", "building_id": "E5"}),

        # --- ограничения ---
        # сплошная запретная зона вокруг E5 (кладбище/охранная зона)
        feat(poly(37.6120, 55.7620, 0.0008, 0.0008),
             {"object_type": "constraint", "object_id": "EZ1", "constraint_type": "forbidden"}),
        # спецпроход: ж/д переезд между кольцом и E4
        feat(poly(37.6160, 55.7586, 0.0008, 0.0002),
             {"object_type": "constraint", "object_id": "EZ2", "constraint_type": "special_passage"}),
        # пересечение с условиями: набережная вдоль севера кольца
        feat(line([[37.6130, 55.7650], [37.6190, 55.7650]]),
             {"object_type": "constraint", "object_id": "EZ3",
              "constraint_type": "crossing", "min_angle_deg": 45}),
    ]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as fh:
        json.dump({"type": "FeatureCollection", "features": features}, fh, ensure_ascii=False)
    print(f"написано: {OUT} ({len(features)} объектов)")


if __name__ == "__main__":
    main()
