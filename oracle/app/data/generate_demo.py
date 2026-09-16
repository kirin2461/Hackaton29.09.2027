"""Генератор реалистичных демо-геоданных (запуск из папки backend/):
    python -m app.data.generate_demo

Перезаписывает buildings.geojson, roads.geojson, heat_networks.geojson.
Координаты — EPSG:32637 (UTM 37N), локальный ноль карты (413020, 6171020).

Здания — не прямоугольники, а реальные формы застройки:
Г-образные, П-образные (с двором-колодцем), Т-образные, с поворотами.
Дороги — извилистые полилинии с разрывами (разрывы важны для
трассировки: без них «объезд» невозможен и варианты A* вырождаются).
"""

import json
import math
from pathlib import Path

OX, OY = 413020.0, 6171020.0
HERE = Path(__file__).resolve().parent

CRS = {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::32637"}}


def to_utm(x, y):
    return [OX + x, OY + y]


def rotate(px, py, deg):
    a = math.radians(deg)
    return (px * math.cos(a) - py * math.sin(a),
            px * math.sin(a) + py * math.cos(a))


def shape_rect(w, d):
    return [(-w/2, -d/2), (w/2, -d/2), (w/2, d/2), (-w/2, d/2)]


def shape_l(w, d):
    """Г-образное: полный прямоугольник минус верхняя правая четверть."""
    return [(-w/2, -d/2), (w/2, -d/2), (w/2, 0), (0, 0),
            (0, d/2), (-w/2, d/2)]


def shape_u(w, d, t=6.0):
    """П-образное здание с двором-колодцем, открытым на север."""
    return [(-w/2, -d/2), (w/2, -d/2), (w/2, d/2), (w/2 - t, d/2),
            (w/2 - t, 0), (-w/2 + t, 0), (-w/2 + t, d/2), (-w/2, d/2)]


def shape_t(w, d):
    """Т-образное: вертикальный корпус + поперечная сверху."""
    tw = w * 0.4
    t = d * 0.35
    return [(-tw/2, -d/2), (tw/2, -d/2), (tw/2, d/2 - t), (w/2, d/2 - t),
            (w/2, d/2), (-w/2, d/2), (-w/2, d/2 - t), (-tw/2, d/2 - t)]


SHAPES = {"rect": shape_rect, "L": shape_l, "U": shape_u, "T": shape_t}

# (id, имя, шаблон, w, d, поворот°, этажи, центр x, y)
BUILDINGS = [
    ("b1",  "Жилой дом 1 (Г-обр.)",  "L",    60, 45,  10, 2,  130, 185),
    ("b2",  "Жилой дом 2 (П-обр.)",  "U",    55, 50,  -5, 12, 130, 400),
    ("b3",  "Жилой дом 3",           "rect", 50, 35,   5, 3,  130, 610),
    ("b4",  "Офис (Т-обр.)",         "T",    55, 45,   0, 3,  320, 180),
    ("b5",  "Жилой дом 5",           "rect", 60, 40,  15, 5,  330, 400),
    ("b6",  "Жилой дом 6 (Г-обр.)",  "L",    50, 50, -12, 12, 320, 600),
    ("b7",  "Торговый центр",        "rect", 55, 38,  -8, 3,  530, 170),
    ("b8",  "Жилой дом 8 (П-обр.)",  "U",    60, 55,   8, 9,  530, 410),
    ("b9",  "Школа",                 "T",    48, 36,   0, 4,  545, 605),
    ("b10", "Жилой дом 10 (Г-обр.)", "L",    55, 45,  20, 2,  720, 180),
    ("b11", "Бизнес-центр",          "rect", 58, 42, -15, 12, 730, 400),
    ("b12", "Жилой дом 12 (Т-обр.)", "T",    55, 50,   5, 9,  730, 610),
    ("b13", "Детский сад",           "rect", 28, 22,  25, 2,  100, 340),
    ("b14", "Жилой дом 14",          "rect", 40, 30,  25, 6,  490, 560),
]


def gen_buildings():
    feats = []
    for bid, name, kind, w, d, rot, floors, cx, cy in BUILDINGS:
        ring = []
        for px, py in SHAPES[kind](w, d):
            rx, ry = rotate(px, py, rot)
            ring.append(to_utm(cx + rx, cy + ry))
        ring.append(ring[0])  # замыкаем кольцо
        feats.append({
            "type": "Feature",
            "properties": {"id": bid, "name": name, "floors": floors},
            "geometry": {"type": "Polygon", "coordinates": [ring]},
        })
    return {"type": "FeatureCollection", "crs": CRS, "features": feats}


# (id, имя, класс, точки полилинии; None в списке = разрыв дороги)
ROADS = [
    ("r0", "ул. Западная", "residential",
     [(40, 0), (55, 200), (35, 400), (50, 600), (40, 760)]),
    ("r1", "ул. Центральная", "residential",
     [(230, 0), (240, 180), (225, 340), None, (215, 460), (235, 600), (225, 760)]),
    ("r2", "ул. Восточная", "residential",
     [(430, 0), (445, 120), (425, 200), None, (440, 340), (420, 500), (435, 640), (430, 760)]),
    ("r3", "ул. Дальняя", "residential",
     [(630, 0), (645, 160), (625, 320), (640, 480), (620, 560), None, (640, 640), (630, 760)]),
    ("r4", "ул. Окраинная", "residential",
     [(830, 0), (845, 250), (825, 520), (830, 760)]),
    ("r10", "пер. Южный", "secondary",
     [(0, 80), (200, 95), (400, 75), (500, 80), None, (620, 70), (860, 85)]),
    ("r11", "пер. Средний", "secondary",
     [(0, 280), (150, 290), (280, 275), None, (400, 285), (650, 270), (860, 280)]),
    ("r12", "пер. Северный", "secondary",
     [(0, 500), (300, 510), None, (380, 495), (520, 505), None, (600, 495), (860, 505)]),
    ("r13", "пер. Верхний", "secondary",
     [(0, 700), (180, 710), None, (300, 695), (550, 705), (860, 695)]),
]


def gen_roads():
    feats = []
    for rid, name, hw, pts in ROADS:
        seg, k = [], 0
        for p in pts + [None]:  # None закрывает сегмент
            if p is None:
                if len(seg) >= 2:
                    feats.append({
                        "type": "Feature",
                        "properties": {"id": rid if k == 0 else f"{rid}_{k}",
                                       "name": name, "highway": hw},
                        "geometry": {"type": "LineString",
                                     "coordinates": [to_utm(x, y) for x, y in seg]},
                    })
                    k += 1
                seg = []
            else:
                seg.append(p)
    return {"type": "FeatureCollection", "crs": CRS, "features": feats}


# Теплосети — с изгибами, вдоль существующих дорог.
NETWORKS = [
    ("h1", "Тепломагистраль ЦТП-1 — ЦТП-2", 300,
     [(45, 285), (150, 292), (225, 280), (330, 283), (430, 285)]),
    ("h2", "Ответвление на северный квартал", 200,
     [(430, 285), (440, 340), (425, 420), (422, 500), (430, 560)]),
    ("h3", "Ответвление на южный квартал", 150,
     [(225, 280), (228, 220), (232, 150), (230, 82)]),
]


def gen_networks():
    feats = []
    for nid, name, dia, pts in NETWORKS:
        feats.append({
            "type": "Feature",
            "properties": {"id": nid, "name": name, "diameter_mm": dia},
            "geometry": {"type": "LineString",
                         "coordinates": [to_utm(x, y) for x, y in pts]},
        })
    return {"type": "FeatureCollection", "crs": CRS, "features": feats}


def main():
    for fname, gen in (("buildings.geojson", gen_buildings),
                       ("roads.geojson", gen_roads),
                       ("heat_networks.geojson", gen_networks)):
        data = gen()
        (HERE / fname).write_text(
            json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{fname}: {len(data['features'])} объектов")


if __name__ == "__main__":
    main()
