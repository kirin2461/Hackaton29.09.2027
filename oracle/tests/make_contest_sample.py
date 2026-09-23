"""Генератор синтетического конкурсного набора (актуальная схема §1).

Район ~1.5 км (EPSG:4326): линейная существующая сеть
«SRC → S0 → C0 → S1 → C1 → S2 → C2 → S3», восемь точек подключения
oks_connection_point с собственными flow_tph, полигоны ОКС как
restriction_type=oks, ограничения по таблице 2. Значения подобраны так,
чтобы сработали все механики актуального техприложения:

  §2.2 — P1, P2, P3, P5 внутри своих полигонов ОКС: финальный прямой
         участок от границы полигона, отступ к своему полигону не
         применяется; чужие полигоны ОКС — отступ 5/7/9 м по ДУ;
  §2.3 — P8: путь ~470 м при расходе 3 т/ч — ДУ повышается с 50 до 125
         (минимальный по расходу И предельной длине, много шагов);
  §2.4 — P5: точка присоединения в 7,8 м от камеры C1 (2 примыкания из 4)
         — врезка в существующую камеру (5 млн ₽ за новый участок);
         остальные — новые камеры на существующих участках;
  §2.5 — P6 внутри парка (запретная зона) — неподключение,
         штраф 100 млн + 500 тыс. × 8 = 104 млн ₽;
  §4   — park (объезд), road (спецпроход K=1,60, полигон+3 м),
         газопровод-линия (K=1,25, ±2 м), railway (запрет, 1,0 м),
         существующая сеть — генерируемый спецпроход K=1,05 (кроме мест
         присоединения);
  §1.2 — кластер P1+P2 (~90 м между точками) — общий ствол с камерой
         разветвления (в варианте «совместное подключение»).
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
        # --- источник и существующая сеть (схема §1.1: id, diameter) ---
        feat(point(37.5000, 55.8700),
             {"object_type": "source", "id": "SRC"}),
        feat(line([[37.5000, 55.8700], [37.5030, 55.8700]]),
             {"object_type": "heat_network", "id": "S0", "diameter": 500}),
        feat(point(37.5030, 55.8700),
             {"object_type": "heat_chamber", "id": "C0"}),
        feat(line([[37.5030, 55.8700], [37.5060, 55.8700]]),
             {"object_type": "heat_network", "id": "S1", "diameter": 200}),
        feat(point(37.5060, 55.8700),
             {"object_type": "heat_chamber", "id": "C1"}),
        feat(line([[37.5060, 55.8700], [37.5090, 55.8700]]),
             {"object_type": "heat_network", "id": "S2", "diameter": 150}),
        feat(point(37.5090, 55.8700),
             {"object_type": "heat_chamber", "id": "C2"}),
        feat(line([[37.5090, 55.8700], [37.5120, 55.8700]]),
             {"object_type": "heat_network", "id": "S3", "diameter": 150}),

        # --- точки подключения ОКС (id, flow_tph) и их полигоны (oks) ---
        # P1 + P2 — кластер (точки ~90 м), общий ствол
        feat(point(37.5080, 55.8735),
             {"object_type": "oks_connection_point", "id": "P1", "flow_tph": 15}),
        feat(poly(37.5080, 55.8735, 0.0004, 0.0003),
             {"object_type": "restriction", "id": "OKS1", "restriction_type": "oks"}),
        feat(point(37.5095, 55.8740),
             {"object_type": "oks_connection_point", "id": "P2", "flow_tph": 20}),
        {"type": "Feature",
         "geometry": {"type": "MultiPolygon", "coordinates": [[[
             [37.5091, 55.8737], [37.5099, 55.8737],
             [37.5099, 55.8743], [37.5091, 55.8743],
             [37.5091, 55.8737]]]]},
         "properties": {"object_type": "restriction", "id": "OKS2",
                        "restriction_type": "oks"}},
        # P3 — восточнее; на пути дорога (спецпроход K=1,60)
        feat(point(37.5140, 55.8690),
             {"object_type": "oks_connection_point", "id": "P3", "flow_tph": 45}),
        feat(poly(37.5140, 55.8690, 0.0004, 0.0003),
             {"object_type": "restriction", "id": "OKS3", "restriction_type": "oks"}),
        # P4 — западнее; на пути газопровод (спецпроход K=1,25)
        feat(point(37.5020, 55.8738),
             {"object_type": "oks_connection_point", "id": "P4", "flow_tph": 90}),
        feat(poly(37.5020, 55.8738, 0.0004, 0.0003),
             {"object_type": "restriction", "id": "OKS4", "restriction_type": "oks"}),
        # P5 — точка в 7,8 м от камеры C1 → врезка в существующую камеру
        feat(point(37.5060, 55.87007),
             {"object_type": "oks_connection_point", "id": "P5", "flow_tph": 20}),
        feat(poly(37.5060, 55.87025, 0.0004, 0.0002),
             {"object_type": "restriction", "id": "OKS5", "restriction_type": "oks"}),
        # P6 — внутри парка (запретная зона) → неподключение (§2.5)
        feat(point(37.5040, 55.8725),
             {"object_type": "oks_connection_point", "id": "P6", "flow_tph": 8}),
        # P8 — дальняя (~470 м от сети): ДУ по предельной длине 50 → 125
        feat(point(37.4925, 55.8700),
             {"object_type": "oks_connection_point", "id": "P8", "flow_tph": 3}),
        feat(poly(37.4925, 55.8700, 0.0003, 0.0002),
             {"object_type": "restriction", "id": "OKS8", "restriction_type": "oks"}),

        # --- пространственные ограничения (таблица 2) ---
        # парк между сетью и кластером P1/P2 — объезд; накрывает P6
        feat(poly(37.5040, 55.8725, 0.0003, 0.0003),
             {"object_type": "restriction", "id": "Z1", "restriction_type": "park"}),
        # газопровод-линия поперёк пути к P4 (спецпроход ±2 м, K=1,25)
        feat(line([[37.5010, 55.8720], [37.5030, 55.8720]]),
             {"object_type": "restriction", "id": "Z2", "restriction_type": "gas_pipeline"}),
        # дорога-полоса поперёк пути к P3 (спецпроход +3 м за границы, K=1,60)
        feat(poly(37.5125, 55.8697, 0.00025, 0.0006),
             {"object_type": "restriction", "id": "Z4", "restriction_type": "road"}),
        # железная дорога на востоке (запрет, 1,0 м) — контроль типа railway
        feat(line([[37.5155, 55.8680], [37.5155, 55.8720]]),
             {"object_type": "restriction", "id": "Z5", "restriction_type": "railway"}),
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
