"""Смета, гидравлика и валидация трассы (Дни 12–14).

После того как A* построил трассу (или пользователь перетянул
узлы трубы gizmo'м), фронтенд присылает полилинию трассы на
POST /api/route/validate. Здесь считаем:

  - длину и число поворотов (>15°);
  - переходы под дорогами (каждый — микротоннелирование, дорого);
  - коллизии со зданиями (по сегментам — для красной подсветки);
  - смету: длина × тариф + переходы + отводы;
  - теплопотери по длине (укрупнённо для DN150–300).

Коэффициенты — демонстрационные, в config.py их можно переопределить
переменными окружения.
"""

from __future__ import annotations

import math
from typing import Any

from shapely.geometry import LineString, Polygon

# --- тарифы (демо, укрупнённые для двухтрубной прокладки) ---
TARIFF_RUB_PER_M = 120_000      # базовая прокладка, ₽/м
ROAD_CROSSING_RUB = 350_000     # переход под дорогой, ₽/шт
TURN_RUB = 45_000               # отвод/компенсатор, ₽/поворот
HEAT_LOSS_KW_PER_M = 0.055      # теплопотери, кВт/м

TURN_ANGLE_DEG = 15.0           # поворотом считаем угол больше этого


def _count_turns(path: list[list[float]]) -> int:
    """Число поворотов полилинии с углом больше TURN_ANGLE_DEG."""
    turns = 0
    for a, b, c in zip(path, path[1:], path[2:]):
        v1 = (b[0] - a[0], b[1] - a[1])
        v2 = (c[0] - b[0], c[1] - b[1])
        l1 = math.hypot(*v1)
        l2 = math.hypot(*v2)
        if l1 < 1e-9 or l2 < 1e-9:
            continue
        cos = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (l1 * l2)))
        if math.degrees(math.acos(cos)) > TURN_ANGLE_DEG:
            turns += 1
    return turns


def validate_path(path: list[list[float]],
                  layers: dict[str, list[dict]]) -> dict[str, Any]:
    """Полная проверка трассы: геометрия, коллизии, смета, гидравлика."""
    if len(path) < 2:
        raise ValueError("Трассе нужно минимум 2 точки")

    line = LineString(path)
    length_m = float(line.length)
    turns = _count_turns(path)

    # Переходы под дорогами: каждое пересечение линии дороги — один переход.
    road_crossings = 0
    for road in layers.get("roads", []):
        road_line = LineString(road["coordinates"])
        inter = line.intersection(road_line)
        if inter.is_empty:
            continue
        if inter.geom_type == "Point":
            road_crossings += 1
        elif inter.geom_type == "MultiPoint":
            road_crossings += len(inter.geoms)
        elif "Line" in inter.geom_type:
            # трасса идёт ВДОЛЬ дороги — это не переход, а штрафной участок
            road_crossings += 1

    # Коллизии со зданиями: для каждого сегмента — пересекает ли здание.
    collision_segments: list[int] = []
    collision_buildings: set[str] = set()
    buildings = [
        (f["id"], Polygon(f["coordinates"]))
        for f in layers.get("buildings", [])
    ]
    for idx, (a, b) in enumerate(zip(path, path[1:])):
        seg = LineString([a, b])
        for bid, poly in buildings:
            # crosses/interior-intersection: касание границы не считаем
            if poly.intersection(seg).length > 1e-6:
                collision_segments.append(idx)
                collision_buildings.add(bid)
                break

    # Смета.
    cost_rub = (
        length_m * TARIFF_RUB_PER_M
        + road_crossings * ROAD_CROSSING_RUB
        + turns * TURN_RUB
    )

    return {
        "length_m": round(length_m, 1),
        "turns": turns,
        "road_crossings": road_crossings,
        "collision": bool(collision_segments),
        "collision_segments": collision_segments,
        "collision_buildings": sorted(collision_buildings),
        "cost_mln_rub": round(cost_rub / 1e6, 2),
        "heat_loss_kw": round(length_m * HEAT_LOSS_KW_PER_M, 1),
        "tariffs": {
            "rub_per_m": TARIFF_RUB_PER_M,
            "road_crossing_rub": ROAD_CROSSING_RUB,
            "turn_rub": TURN_RUB,
            "heat_loss_kw_per_m": HEAT_LOSS_KW_PER_M,
        },
    }
