"""Дополнительный синтетический набор для репетиции (официальная схема §2.1).

Другой район (~7 км восточнее), ДРУГАЯ топология: кольцевая сеть
«RSRC → R0 → RC0 → R1 → RC1 → R2 → RC2 → R3 → RC3 → R4», 5 ОКС:
  - E1, E2, E3 — цепочка из трёх ОКС вдоль одной улицы (кластер 60 т/ч,
    врезка в R2 → цепочка проходит R1);
  - E4 — крупный ОКС (200 т/ч) → врезка в СЕРЕДИНУ R1 → ЧАСТИЧНАЯ
    реконструкция R1 (250+60+200=510 > 437,4 → Ду400, кусок ~125 м),
    R2 НЕ реконструируется (180+60=240 ≤ 274,9);
  - E5 — ОКС ВНУТРИ запрещённой территории → unconnected,
    штраф §8.3 = 100 млн + 500 тыс. × 10 = 105 млн ₽.
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
        # --- источник и кольцевая существующая сеть ---
        feat(point(37.6100, 55.7600),
             {"object_type": "source", "id": "RSRC"}),
        feat(line([[37.6100, 55.7600], [37.6140, 55.7600]]),
             {"object_type": "heat_network", "id": "R0",
              "diameter": 600, "flow_tph": 1100, "upstream_object_id": "RSRC"}),
        feat(point(37.6140, 55.7600),
             {"object_type": "heat_chamber", "id": "RC0",
              "diameter": 600, "upstream_object_id": "R0"}),
        feat(line([[37.6140, 55.7600], [37.6180, 55.7600]]),
             {"object_type": "heat_network", "id": "R1",
              "diameter": 300, "flow_tph": 250, "upstream_object_id": "RC0"}),
        feat(point(37.6180, 55.7600),
             {"object_type": "heat_chamber", "id": "RC1",
              "diameter": 300, "upstream_object_id": "R1"}),
        feat(line([[37.6180, 55.7600], [37.6180, 55.7640]]),
             {"object_type": "heat_network", "id": "R2",
              "diameter": 250, "flow_tph": 180, "upstream_object_id": "RC1"}),
        feat(point(37.6180, 55.7640),
             {"object_type": "heat_chamber", "id": "RC2",
              "diameter": 250, "upstream_object_id": "R2"}),
        feat(line([[37.6180, 55.7640], [37.6140, 55.7640]]),
             {"object_type": "heat_network", "id": "R3",
              "diameter": 200, "flow_tph": 120, "upstream_object_id": "RC2"}),
        feat(point(37.6140, 55.7640),
             {"object_type": "heat_chamber", "id": "RC3",
              "diameter": 200, "upstream_object_id": "R3"}),
        # обратная ветвь кольца (в цепочку к источнику не входит)
        feat(line([[37.6140, 55.7640], [37.6140, 55.7600]]),
             {"object_type": "heat_network", "id": "R4",
              "diameter": 200, "flow_tph": 120, "upstream_object_id": "RC3"}),

        # --- перспективные ОКС ---
        # E1–E3 — цепочка вдоль улицы северо-восточнее R1 (кластер 60 т/ч)
        feat(poly(37.6155, 55.7622, 0.0004, 0.0003),
             {"object_type": "oks_future", "id": "E1", "flow_tph": 20, "heat_load": 10.8}),
        feat(point(37.6155, 55.7615),
             {"object_type": "oks_connection_point", "id": "ECP1", "oks_id": "E1"}),
        feat(poly(37.6165, 55.7624, 0.0004, 0.0003),
             {"object_type": "oks_future", "id": "E2", "flow_tph": 25, "heat_load": 13.5}),
        feat(point(37.6165, 55.7617),
             {"object_type": "oks_connection_point", "id": "ECP2", "oks_id": "E2"}),
        feat(poly(37.6175, 55.7622, 0.0004, 0.0003),
             {"object_type": "oks_future", "id": "E3", "flow_tph": 15, "heat_load": 8.1}),
        feat(point(37.6175, 55.7615),
             {"object_type": "oks_connection_point", "id": "ECP3", "oks_id": "E3"}),
        # E4 — крупный ОКС южнее: врезка в середину R1 → частичная
        # реконструкция (510 > 437,4 → Ду500), дорога на пути (K=1,60)
        feat(poly(37.6160, 55.7565, 0.0004, 0.0003),
             {"object_type": "oks_future", "id": "E4", "flow_tph": 200, "heat_load": 108.0}),
        feat(point(37.6160, 55.7573),
             {"object_type": "oks_connection_point", "id": "ECP4", "oks_id": "E4"}),
        # E5 — ВНУТРИ запрещённой территории → unconnected (штраф 105 млн ₽)
        feat(poly(37.6120, 55.7620, 0.0003, 0.0003),
             {"object_type": "oks_future", "id": "E5", "flow_tph": 10, "heat_load": 5.4}),
        feat(point(37.6120, 55.7620),
             {"object_type": "oks_connection_point", "id": "ECP5", "oks_id": "E5"}),

        # --- пространственные ограничения (таблица 5.1) ---
        feat(poly(37.6120, 55.7620, 0.0008, 0.0008),
             {"object_type": "restriction", "id": "EZ1",
              "restriction_type": "prohibited_site"}),
        feat(poly(37.6160, 55.7586, 0.0008, 0.0002),
             {"object_type": "restriction", "id": "EZ2", "restriction_type": "road"}),
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
