"""Калькулятор стоимости варианта и ранжирование (разделы 8–9).

Калькуляция — строго по статьям §10.7:
  construction_cost            — новые линейные участки;
  chamber_construction_cost    — новые камеры (шкала §8.2);
  tie_in_cost                  — врезки (5 млн ₽ каждая, §8.2);
  reconstruction_cost          — реконструкция линейных участков (§7);
  chamber_reconstruction_cost  — реконструкция камер (§8.2);
  unconnected_penalty          — штрафы §8.3: 100 млн + 500 тыс.×G за ОКС;
  calculated_cost              — сумма всех статей.

Показатель ранжирования (раздел 9):
  S = 0,7·C/25 000 000 + 0,3·L/100,  L = новая сеть + реконструкция;
  меньший S — лучший вариант (rank 1).
"""

from __future__ import annotations

from .refdata import RefData


def variant_costs(new_segments, new_chambers, taps, recon, unconnected,
                  ref: RefData) -> dict:
    """Развёрнутая калькуляция одного варианта (статьи §10.7)."""
    construction = sum(s.cost_rub for s in new_segments)
    chamber_construction = sum(c["cost_rub"] for c in new_chambers)
    # §8.2: каждая врезка — 5 млн ₽, вне зависимости от вида
    tie_in = sum(t.tap_cost_rub for t in taps)
    reconstruction = recon.segments_cost_rub
    chamber_reconstruction = recon.chambers_cost_rub
    penalty = sum(ref.unconnected_penalty(u.get("flow_tph", 0.0)) for u in unconnected)
    total = (construction + chamber_construction + tie_in
             + reconstruction + chamber_reconstruction + penalty)

    return {
        "construction_cost": round(construction, 2),
        "chamber_construction_cost": round(chamber_construction, 2),
        "tie_in_cost": round(tie_in, 2),
        "reconstruction_cost": round(reconstruction, 2),
        "chamber_reconstruction_cost": round(chamber_reconstruction, 2),
        "unconnected_penalty": round(penalty, 2),
        "calculated_cost": round(total, 2),
    }


def variant_lengths_m(new_segments, recon) -> dict:
    """Длины варианта (§10.7): новая сеть, реконструкция, сумма."""
    new_len = round(sum(s.length_m for s in new_segments), 1)
    recon_len = round(sum(s.length_m for s in recon.segments), 1)
    return {
        "new_network_length": new_len,
        "reconstruction_length": recon_len,
        "length": round(new_len + recon_len, 1),
    }


def rank_variants(variants: list, ref: RefData) -> None:
    """Ранжирование in-place по разделу 9 (меньший S — лучший)."""
    if not variants:
        return
    for v in variants:
        v["score"] = round(ref.score(v["costs"]["calculated_cost"],
                                     v["lengths"]["length"]), 6)
    variants.sort(key=lambda v: v["score"])
    for idx, v in enumerate(variants, start=1):
        v["rank"] = idx
        v["is_recommended"] = idx == 1
