"""Fail-fast валидация конфигов техприложения при старте geo-engine.

Принцип (риск №2 плана): любое расхождение конфига с техприложением должно
рвать запуск сервиса с понятной ошибкой, а не всплывать на середине расчёта.

Использование:
    from app.config_validation import load_and_validate
    cfg = load_and_validate("config/")   # на старте FastAPI-приложения
"""
from __future__ import annotations

import os
import yaml


class ConfigError(ValueError):
    """Конфиг противоречит техприложению или сам себе."""


def _load(cfg_dir: str, name: str) -> dict:
    path = os.path.join(cfg_dir, name)
    if not os.path.exists(path):
        raise ConfigError(f"Нет файла конфигурации: {path}")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _check_diameters(d: dict) -> None:
    rows = d["diameters"]
    dus = [r["du"] for r in rows]
    if dus != sorted(dus):
        raise ConfigError("diameters.yaml: ДУ должны идти по возрастанию")
    for a, b in zip(rows, rows[1:]):
        for key in ("capacity_tph", "max_length_m",
                    "new_cost_rub_per_m", "reconstruction_cost_rub_per_m"):
            if b[key] <= a[key]:
                raise ConfigError(
                    f"diameters.yaml: {key} не растёт монотонно "
                    f"между ДУ{a['du']} и ДУ{b['du']}")
    for r in rows:
        # габариты табл. 4.2: ширина = 2*оболочка + просвет, высота = оболочка
        w = round(2 * r["shell_outer_diameter_m"] + r["shell_gap_m"], 3)
        if abs(w - r["pair_width_m"]) > 1e-9 or \
           abs(r["shell_outer_diameter_m"] - r["pair_height_m"]) > 1e-9:
            raise ConfigError(
                f"diameters.yaml: габариты ДУ{r['du']} не сходятся с табл. 4.2")


def _check_cost(c: dict, d: dict) -> None:
    w = c["ranking"]
    if abs(w["cost_weight"] + w["length_weight"] - 1.0) > 1e-9:
        raise ConfigError("cost.yaml: веса ранжирования должны давать в сумме 1.0")
    scale = c["chamber_cost_scale_rub"]
    dus = sorted(r["du"] for r in d["diameters"])
    for du in dus:  # каждый допустимый ДУ должен попадать ровно в одну ступень
        hits = [s for s in scale if s["du_min"] <= du <= s["du_max"]]
        if len(hits) != 1:
            raise ConfigError(
                f"cost.yaml: ДУ{du} попадает в {len(hits)} ступеней шкалы камер")
    if c["max_sections_per_chamber"] != 4:
        raise ConfigError("cost.yaml: по §3 на камеру приходится ≤4 участков")


def _check_constraints(rules: dict) -> None:
    for rtype, r in rules["restriction_rules"].items():
        if r["rule"] not in ("forbidden", "special_passage"):
            raise ConfigError(f"constraints.yaml: {rtype}: неизвестное правило")
        if r["rule"] == "special_passage":
            if not (0 < r.get("k_special", 0)):
                raise ConfigError(f"constraints.yaml: {rtype}: нужен k_special > 0")
            if "depth_rule" not in r:
                raise ConfigError(f"constraints.yaml: {rtype}: нет depth_rule")
        if r["rule"] == "forbidden" and "min_distance_m" not in r \
                and "min_distance_by_du" not in r:
            raise ConfigError(f"constraints.yaml: {rtype}: нет мин. расстояния")


def load_and_validate(cfg_dir: str) -> dict:
    cfg = {
        "diameters":   _load(cfg_dir, "diameters.yaml"),
        "constraints": _load(cfg_dir, "constraints.yaml"),
        "cost":        _load(cfg_dir, "cost.yaml"),
        "depth":       _load(cfg_dir, "depth.yaml"),
        "input_schema":  _load(cfg_dir, "input_schema.yaml"),
        "output_schema": _load(cfg_dir, "output_schema.yaml"),
    }
    _check_diameters(cfg["diameters"])
    _check_cost(cfg["cost"], cfg["diameters"])
    _check_constraints(cfg["constraints"])
    return cfg
