"""Загрузка справочников техприложения из YAML-конфига (Спринт 2).

Все справочники — во внешнем файле reference.yaml, НЕ в коде (§2.14 ТЗ):
при изменении техприложения правится только конфиг.
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
        # Таблица диаметров, отсортированная по возрастанию Ду
        self.diameters = sorted(raw["diameters"], key=lambda d: d["dn_mm"])
        self.tariffs = raw["tariffs_rub"]
        self.rules = raw["rules"]

    # ---- диаметры / гидравлика ----

    def diameter_for_flow(self, flow_tph: float) -> dict:
        """Минимальный Ду, пропускная способность которого покрывает расход."""
        for d in self.diameters:
            if d["max_flow_tph"] >= flow_tph:
                return d
        return self.diameters[-1]  # берём максимальный; факт нехватки — в warnings

    def max_len_for(self, dn_mm: float) -> float:
        for d in self.diameters:
            if d["dn_mm"] == dn_mm:
                return float(d["max_len_m"])
        return float(self.diameters[-1]["max_len_m"])

    # ---- тарифы ----

    def lay_tariff(self, dn_mm: float) -> float:
        table = self.tariffs["lay_per_m"]
        # Ключи YAML — int; на всякий случай нормализуем
        return float(table.get(int(dn_mm), table.get(str(int(dn_mm)), 0.0)))

    def tariff(self, key: str) -> float:
        return float(self.tariffs[key])

    def rule(self, key: str) -> float:
        return float(self.rules[key])
