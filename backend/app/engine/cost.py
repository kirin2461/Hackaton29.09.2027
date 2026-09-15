"""Полный калькулятор стоимости варианта (§2.7 ТЗ, Спринт 3).

Калькуляция по техприложению (все ставки — из reference.yaml):
  - новые участки (по диаметрам и методам прокладки, включая спецпроходы);
  - новые камеры (врезочные и разветвительные) и технические узлы;
  - врезки в существующие камеры;
  - реконструкция существующих участков и камер;
  - штраф за каждый неподключённый ОКС.

Показатель ранжирования (§2.8): 70% стоимость + 30% протяжённость
строительных работ (нормированные по вариантам).
"""

from __future__ import annotations

from .refdata import RefData

WEIGHT_COST = 0.7
WEIGHT_LENGTH = 0.3


def variant_costs(new_segments, new_chambers, taps, recon, unconnected,
                  ref: RefData) -> dict:
    """Развёрнутая калькуляция одного варианта."""
    cost_new = sum(s.cost_rub for s in new_segments)
    cost_chambers = sum(c["cost_rub"] for c in new_chambers)
    cost_taps = sum(t.tap_cost_rub for t in taps)
    cost_recon = recon.total_cost_rub
    cost_penalty = len(unconnected) * ref.tariff("unconnected_penalty")
    total = cost_new + cost_chambers + cost_taps + cost_recon + cost_penalty

    return {
        "new_segments": round(cost_new, 2),
        "new_chambers": round(cost_chambers, 2),
        "tappings": round(cost_taps, 2),
        "reconstruction": round(cost_recon, 2),
        "unconnected_penalty": round(cost_penalty, 2),
        "total": round(total, 2),
    }


def variant_length_m(new_segments) -> float:
    """Протяжённость строительных работ (новые участки)."""
    return round(sum(s.length_m for s in new_segments), 1)


def rank_variants(variants: list) -> None:
    """Ранжирование in-place: score = 0.7·норм.стоимость + 0.3·норм.длина.

    Меньший score — лучший вариант (rank 1 = рекомендуемый).
    """
    if not variants:
        return
    max_cost = max(v["costs"]["total"] for v in variants) or 1.0
    max_len = max(v["length_total_m"] for v in variants) or 1.0
    for v in variants:
        v["score"] = round(
            WEIGHT_COST * v["costs"]["total"] / max_cost
            + WEIGHT_LENGTH * v["length_total_m"] / max_len, 4)
    variants.sort(key=lambda v: v["score"])
    for idx, v in enumerate(variants, start=1):
        v["rank"] = idx
        v["is_recommended"] = idx == 1
