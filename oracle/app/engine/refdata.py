"""Загрузка справочников техприложения из YAML-конфига.

Все справочники — во внешнем файле reference.yaml, НЕ в коде (§2.14 ТЗ):
при изменении техприложения правится только конфиг. Значения соответствуют
официальному техприложению ЛЦТ-2026 (таблицы 4.1, 4.2, 5.1; разделы 8–9).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

DEFAULT_REF_PATH = Path(__file__).parent / "reference.yaml"


class RefData:
    """Типизированный доступ к справочникам техприложения."""

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else DEFAULT_REF_PATH
        with self.path.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
        # Таблица 4.1, отсортированная по возрастанию Ду
        self.diameters = sorted(raw["diameters"], key=lambda d: d["dn_mm"])
        # Таблица 4.2: габариты по Ду
        self.envelopes = {int(e["dn_mm"]): e for e in raw["envelopes"]}
        # Таблица 5.1
        self.restrictions = raw.get("restrictions", {})
        self.tariffs = raw["tariffs_rub"]
        self.scoring = raw["scoring"]
        self.rules = raw["rules"]
        self.depth = raw.get("depth", {})

    # ---- диаметры / гидравлика (таблица 4.1) ----

    def diameter_for_flow(self, flow_tph: float) -> dict:
        """Минимальный Ду, пропускная способность которого покрывает расход."""
        for d in self.diameters:
            if d["max_flow_tph"] >= flow_tph:
                return d
        return self.diameters[-1]  # берём максимальный; факт нехватки — в warnings

    def diameter_entry(self, dn_mm: float) -> dict:
        for d in self.diameters:
            if d["dn_mm"] == dn_mm:
                return d
        return self.diameters[-1]

    def next_diameter(self, dn_mm: float) -> dict:
        """Следующий больший Ду (для повышения при превышении предельной длины)."""
        bigger = [d for d in self.diameters if d["dn_mm"] > dn_mm]
        return bigger[0] if bigger else self.diameters[-1]

    def max_len_for(self, dn_mm: float) -> float:
        return float(self.diameter_entry(dn_mm)["max_len_m"])

    # ---- габариты (таблица 4.2) ----

    def envelope_width_m(self, dn_mm: float) -> float:
        return float(self.envelopes.get(int(dn_mm), self.envelopes[max(self.envelopes)])["width_m"])

    def envelope_height_m(self, dn_mm: float) -> float:
        return float(self.envelopes.get(int(dn_mm), self.envelopes[max(self.envelopes)])["height_m"])

    # ---- ограничения (таблица 5.1) ----

    def restriction_rule(self, restriction_type: str) -> Optional[dict]:
        return self.restrictions.get(restriction_type)

    def min_distance_m(self, restriction_type: str, dn_mm: float = 0) -> float:
        """Минимальное горизонтальное расстояние; для ОКС — ступенями по Ду."""
        rule = self.restrictions.get(restriction_type) or {}
        if "min_distance_by_dn" in rule:
            for step in rule["min_distance_by_dn"]:
                if dn_mm <= step["max_dn_mm"]:
                    return float(step["distance_m"])
            return float(rule["min_distance_by_dn"][-1]["distance_m"])
        return float(rule.get("min_distance_m", 1.0))

    # ---- тарифы (раздел 8) ----

    def lay_tariff(self, dn_mm: float) -> float:
        """Ставка нового строительства, ₽/м (таблица 4.1)."""
        return float(self.diameter_entry(dn_mm)["cost_new_rub_m"])

    def recon_tariff(self, dn_mm: float) -> float:
        """Ставка реконструкции по ТРЕБУЕМОМУ диаметру, ₽/м (§7, таблица 4.1)."""
        return float(self.diameter_entry(dn_mm)["cost_recon_rub_m"])

    def tie_in_cost(self) -> float:
        """§8.2: стоимость одной врезки (любого вида)."""
        return float(self.tariffs["tie_in"])

    def chamber_cost(self, max_dn_mm: float) -> float:
        """§8.2: стоимость камеры по наибольшему Ду примыкающих участков."""
        for step in self.tariffs["chamber_cost_scale"]:
            if max_dn_mm <= step["max_dn_mm"]:
                return float(step["cost_rub"])
        return float(self.tariffs["chamber_cost_scale"][-1]["cost_rub"])

    def unconnected_penalty(self, flow_tph: float) -> float:
        """§8.3: штраф за неподключённый ОКС = 100 млн + 500 тыс. × G."""
        return float(self.tariffs["unconnected_penalty_base"]) \
            + float(self.tariffs["unconnected_penalty_per_tph"]) * flow_tph

    def tariff(self, key: str) -> float:
        return float(self.tariffs[key])

    def rule(self, key: str) -> float:
        return float(self.rules[key])

    # ---- ранжирование (раздел 9) ----

    def score(self, calculated_cost_rub: float, length_m: float) -> float:
        """S = w_c·C/C0 + w_l·L/L0; меньше — лучше."""
        s = self.scoring
        return (float(s["weight_cost"]) * calculated_cost_rub / float(s["cost_norm_rub"])
                + float(s["weight_length"]) * length_m / float(s["length_norm_m"]))

    # ---- задание на глубину (раздел 6, доп. задача) ----

    def depth_rule(self, key: str, default: float) -> float:
        return float(self.depth.get(key, default))

    def depth_k(self, depth_m: float) -> float:
        """Kгл = 1 + rate·(h − free) при h > free, иначе 1 (без скидки за мельче)."""
        free = self.depth_rule("free_depth_m", 3.0)
        if depth_m <= free:
            return 1.0
        return 1.0 + self.depth_rule("depth_cost_rate", 0.10) * (depth_m - free)
