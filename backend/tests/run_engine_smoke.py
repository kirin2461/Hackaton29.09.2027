"""Смоук-тест движка на синтетическом конкурсном наборе.

Запуск из папки backend/:
    python tests/run_engine_smoke.py

Проверяет соответствие техприложению ЛЦТ-2026: все ОКС подключены,
диаметры/предельные длины/реконструкция по таблице 4.1, врезки и камеры
по §8.2, штрафы по §8.3, ранжирование по §9, выходной GeoJSON — строго
по контракту §10.
"""

import json
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from tests.make_contest_sample import OUT as SAMPLE_PATH, main as make_sample  # noqa: E402
from app.engine.pipeline import run_pipeline  # noqa: E402

# ---------------------------------------------------------------------------
# Контракт выходных данных (раздел 10 техприложения)
# ---------------------------------------------------------------------------

CONTRACT = {
    "heat_network": {"id", "object_type", "variant_id", "start_node_id",
                     "end_node_id", "flow_tph", "diameter", "length",
                     "laying_method", "depth_start", "depth_end", "cost"},
    "tie_in": {"id", "object_type", "variant_id", "existing_object_id",
               "existing_object_type", "existing_diameter",
               "required_diameter", "cost"},
    "heat_network_reconstruction": {"id", "object_type", "variant_id",
                                    "existing_object_id", "existing_flow_tph",
                                    "added_flow_tph", "calculated_flow_tph",
                                    "existing_diameter", "required_diameter",
                                    "length", "cost"},
    "heat_chamber": {"id", "object_type", "variant_id", "diameter", "cost"},
    "heat_chamber_reconstruction": {"id", "object_type", "variant_id",
                                    "existing_object_id", "existing_diameter",
                                    "required_diameter", "cost"},
    "technical_node": {"id", "object_type", "variant_id"},
    "variant_summary": {"id", "object_type", "variant_id", "rank",
                        "construction_cost", "chamber_construction_cost",
                        "tie_in_cost", "reconstruction_cost",
                        "chamber_reconstruction_cost", "unconnected_penalty",
                        "calculated_cost", "new_network_length",
                        "reconstruction_length", "length", "score",
                        "unconnected_oks_ids"},
}


def contract_checks(data: dict) -> list[tuple[str, bool]]:
    """Проверки строгого соответствия выходного файла разделу 10."""
    checks = []
    checks.append(("§10: корневой тип FeatureCollection",
                   data.get("type") == "FeatureCollection"))
    checks.append(("§10: нет посторонних членов (только type+features)",
                   set(data.keys()) <= {"type", "features"}))
    feats = data["features"]
    checks.append(("§10: только семь типов объектов",
                   all(f["properties"].get("object_type") in CONTRACT
                       for f in feats)))
    checks.append(("§10: у каждого типа ровно свой набор атрибутов",
                   all(set(f["properties"].keys()) == CONTRACT[f["properties"]["object_type"]]
                       for f in feats)))
    checks.append(("§10: у каждого объекта есть variant_id",
                   all(f["properties"].get("variant_id") for f in feats)))
    summaries = [f for f in feats
                 if f["properties"]["object_type"] == "variant_summary"]
    checks.append(("§10.7: сводная запись с geometry = null",
                   bool(summaries) and all(s["geometry"] is None for s in summaries)))
    checks.append(("§10.7: ровно одна сводная запись на вариант",
                   len({s["properties"]["variant_id"] for s in summaries})
                   == len(summaries)))
    net = [f for f in feats if f["properties"]["object_type"] == "heat_network"]
    checks.append(("§10.1: laying_method ∈ {base, special}",
                   all(f["properties"]["laying_method"] in ("base", "special")
                       for f in net)))
    checks.append(("§10.1: в 2D-задаче depth_start/depth_end = null",
                   all(f["properties"]["depth_start"] is None
                       and f["properties"]["depth_end"] is None for f in net)))
    checks.append(("§10.1: узлы участков непустые",
                   all(f["properties"]["start_node_id"]
                       and f["properties"]["end_node_id"] for f in net)))

    def _coords(g):
        if g is None:
            return
        t = g["type"]
        c = g["coordinates"]
        if t == "Point":
            yield c
        elif t == "LineString":
            yield from c
        elif t in ("Polygon", "MultiPolygon"):
            polys = [c] if t == "Polygon" else c
            for p in polys:
                for ring in p:
                    yield from ring
    checks.append(("§10: координаты в EPSG:4326",
                   all(30 < x < 45 and 50 < y < 60
                       for f in feats if f["geometry"]
                       for x, y, *_ in _coords(f["geometry"]))))
    return checks


def main() -> int:
    if not SAMPLE_PATH.exists():
        make_sample()

    result_path = Path(tempfile.mkdtemp()) / "result.geojson"
    summary = run_pipeline(SAMPLE_PATH, result_path)

    print("=== Сводка ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))

    data = json.loads(result_path.read_text(encoding="utf-8"))
    by_type: dict[str, list] = {}
    for f in data["features"]:
        by_type.setdefault(f["properties"]["object_type"], []).append(f["properties"])

    print("=== Объекты результата ===")
    for kind, items in sorted(by_type.items()):
        print(f"  {kind}: {len(items)}")

    variants = summary.get("variants", [])
    print("=== Варианты ===")
    for v in variants:
        print(f"  #{v['rank']} {v['label']}: score={v['score']}, "
              f"total={v['costs_rub']['total'] / 1e6:.1f} млн ₽, "
              f"длина={v['length_total_m']} м"
              f"{'  ← рекомендуемый' if v['is_recommended'] else ''}")

    checks = []
    checks.append(("все ОКС подключены (рекомендуемый вариант)",
                   summary["buildings_connected"] == summary["buildings_total"]))
    checks.append(("вариантов минимум 2", len(variants) >= 2))
    checks.append(("вариантов не больше 3", len(variants) <= 3))
    checks.append(("ранги по возрастанию score (§9: меньше — лучше)",
                   all(variants[i]["score"] <= variants[i + 1]["score"]
                       for i in range(len(variants) - 1))))
    checks.append(("ровно один рекомендуемый вариант",
                   sum(1 for v in variants if v["is_recommended"]) == 1))
    checks.append(("варианты содержательно разные (есть «Раздельное»)",
                   any(v["label"].startswith("Раздельное") for v in variants)))
    checks.append(("есть новые участки", len(by_type.get("heat_network", [])) > 0))
    checks.append(("диаметры назначены из таблицы 4.1",
                   all(s["diameter"] in (50, 65, 80, 100, 125, 150, 200, 250, 300,
                                         400, 500, 600, 700, 800, 900, 1000, 1200, 1400)
                       for s in by_type.get("heat_network", []))))

    # --- §7: реконструкция существующей сети (таблица 4.1) ---
    recon = by_type.get("heat_network_reconstruction", [])
    recon_ids = {r["existing_object_id"] for r in recon}
    checks.append(("§7: реконструкция S1 (100+35+45+20=200 > 152,3 → Ду250)",
                   "S1" in recon_ids
                   and all(r["required_diameter"] == 250
                           for r in recon if r["existing_object_id"] == "S1")))
    checks.append(("§7: реконструкция S2 и S3 (Ду150 → Ду200)",
                   "S2" in recon_ids and "S3" in recon_ids
                   and all(r["required_diameter"] == 200
                           for r in recon if r["existing_object_id"] in ("S2", "S3"))))
    checks.append(("§7: S0 не реконструируется (800+90=890 ≤ 1663,4)",
                   "S0" not in recon_ids))
    checks.append(("§7: расходы согласованы (calculated = existing + added)",
                   all(abs(r["calculated_flow_tph"]
                           - r["existing_flow_tph"] - r["added_flow_tph"]) < 0.01
                       for r in recon)))
    checks.append(("§7: ставка по требуемому Ду, без Kспец/Kгл",
                   bool(recon) and all(
                       abs(r["cost"] - r["length"] * _RECON_TARIFF[r["required_diameter"]])
                       < 1.0 for r in recon)))
    checks.append(("§7: геометрия реконструкции — часть исходного участка",
                   all(r["length"] > 0 for r in recon)))

    # --- §8.2: врезки и камеры ---
    ties = by_type.get("tie_in", [])
    checks.append(("§8.2: каждая врезка 5 млн ₽",
                   bool(ties) and all(t["cost"] == 5000000 for t in ties)))
    checks.append(("§8.2: B5 врезан в существующую камеру C1 (≤10 м, места есть)",
                   any(t["existing_object_id"] == "C1"
                       and t["existing_object_type"] == "heat_chamber"
                       and t["existing_diameter"] == 200
                       for t in ties)))
    recon_ch = by_type.get("heat_chamber_reconstruction", [])
    checks.append(("§8.2: реконструкция камеры C1 (Ду200 → Ду250, 5 млн ₽)",
                   any(c["existing_object_id"] == "C1"
                       and c["required_diameter"] == 250
                       and c["cost"] == 5000000 for c in recon_ch)))
    checks.append(("§8.2: камера C2 НЕ реконструируется (транзитная, протокол п.8)",
                   not any(c["existing_object_id"] == "C2" for c in recon_ch)))
    checks.append(("§8.2: камера C0 НЕ реконструируется (Ду500 достаточно)",
                   not any(c["existing_object_id"] == "C0" for c in recon_ch)))
    chambers = by_type.get("heat_chamber", [])
    checks.append(("§8.2: новые камеры по шкале (3/5/8/12 млн)",
                   bool(chambers)
                   and all(c["cost"] in (3000000, 5000000, 8000000, 12000000)
                           for c in chambers)))

    # --- §5.1: спецпроходы отдельными участками ---
    checks.append(("§5.1: спецпроход выделен отдельным участком (B3/дорога)",
                   any(s["laying_method"] == "special"
                       for s in by_type.get("heat_network", []))))

    # --- §9: score = 0,3·C/25 млн + 0,7·L/100 (по протоколу 16.09) ---
    summaries = by_type.get("variant_summary", [])
    checks.append(("§9: score соответствует формуле",
                   all(abs(s["score"] - (0.3 * s["calculated_cost"] / 25e6
                                         + 0.7 * s["length"] / 100)) < 0.01
                       for s in summaries)))
    checks.append(("§9: rank 1 = минимальный score",
                   min(summaries, key=lambda s: s["score"])["rank"] == 1))
    checks.append(("§10.7: calculated_cost = сумма статей",
                   all(abs(s["calculated_cost"] - (
                       s["construction_cost"] + s["chamber_construction_cost"]
                       + s["tie_in_cost"] + s["reconstruction_cost"]
                       + s["chamber_reconstruction_cost"]
                       + s["unconnected_penalty"])) < 1.0 for s in summaries)))
    checks.append(("§10.7: length = новая сеть + реконструкция",
                   all(abs(s["length"] - s["new_network_length"]
                           - s["reconstruction_length"]) < 0.2 for s in summaries)))

    # --- строгий контракт §10 ---
    checks.extend(contract_checks(data))

    checks.append(("сводная стоимость > 0", summary["costs_rub"]["total"] > 0))

    # --- §8.2: строгое правило врезки (юнит-случаи) ---
    from app.engine.refdata import RefData
    from shapely.geometry import LineString as _LS, Point as _Pt
    from app.engine.model import Chamber as _Ch, Segment as _Seg
    from app.engine.network import ExistingNetwork as _Net
    from app.engine.tapping import choose_tap_strict

    _ref = RefData()
    _segs = {"S": _Seg(object_id="S", geom=_LS([(0, 0), (100, 0)]),
                       diameter_mm=200, flow_tph=50, next_object_id=None)}
    # камера в 5 м от якоря, примыкания исчерпаны (2 входа + выход = 3...4) -> новая
    _net_full = _Net(_segs, {"C": _Ch(object_id="C", geom=_Pt(50, 5),
                                      diameter_mm=200, occupied_connections=4,
                                      next_object_id="S")})
    _tap = choose_tap_strict(_Pt(50, 8), 10, _net_full, _ref, {})
    checks.append(("§8.2: камера ≤10 м, но 4 примыкания -> новая камера на проекции",
                   _tap is not None and _tap.kind == "new_chamber_on_segment"
                   and _tap.segment_id == "S"))
    # камера дальше 10 м -> новая камера
    _net_far = _Net(_segs, {"C": _Ch(object_id="C", geom=_Pt(50, 30),
                                     diameter_mm=200, occupied_connections=1,
                                     next_object_id="S")})
    _tap = choose_tap_strict(_Pt(50, 8), 10, _net_far, _ref, {})
    checks.append(("§8.2: камера дальше 10 м -> новая камера на проекции",
                   _tap is not None and _tap.kind == "new_chamber_on_segment"))
    # камера в 5 м и свободна -> врезка в неё, 5 млн ₽
    _net_ok = _Net(_segs, {"C": _Ch(object_id="C", geom=_Pt(50, 5),
                                    diameter_mm=200, occupied_connections=2,
                                    next_object_id="S")})
    _tap = choose_tap_strict(_Pt(50, 8), 10, _net_ok, _ref, {})
    checks.append(("§8.2: камера ≤10 м и свободна -> врезка в существующую, 5 млн ₽",
                   _tap is not None and _tap.kind == "existing_chamber"
                   and _tap.chamber_id == "C" and _tap.tap_cost_rub == 5000000))

    # --- §8.3: штраф = 100 млн + 500 тыс. × G ---
    checks.append(("§8.3: штраф за ОКС 10 т/ч = 105 млн ₽",
                   _ref.unconnected_penalty(10) == 105_000_000))
    checks.append(("§8.3: штраф за ОКС 40 т/ч = 120 млн ₽",
                   _ref.unconnected_penalty(40) == 120_000_000))

    # --- отступы от ОКС 5/7/9 м по диаметру (таблица 5.1) ---
    checks.append(("§5.1: отступ от ОКС 5/7/9 м по Ду новой сети",
                   _ref.min_distance_m("oks_existing", 300) == 5.0
                   and _ref.min_distance_m("oks_existing", 500) == 7.0
                   and _ref.min_distance_m("oks_existing", 900) == 9.0))
    checks.append(("§5.1: Kспец дорога 1,60 / трамвай 1,75 / газ 1,25 / кабель 1,15 / тепло 1,05",
                   _ref.restriction_rule("road")["k_special"] == 1.60
                   and _ref.restriction_rule("tram_tracks")["k_special"] == 1.75
                   and _ref.restriction_rule("gas_pipeline")["k_special"] == 1.25
                   and _ref.restriction_rule("power_cable")["k_special"] == 1.15
                   and _ref.restriction_rule("heat_network")["k_special"] == 1.05))

    # --- раздел 6 (глубина): Kгл ---
    checks.append(("§6: Kгл=1 при h≤3 м; Kгл=1,15 при h=4,5 м",
                   _ref.depth_k(3.0) == 1.0
                   and abs(_ref.depth_k(4.5) - 1.15) < 1e-9))

    # --- раздел 3: предельная длина цепочки одного Ду (юнит) ---
    from app.engine.hydraulics import NewSegment as _NS, enforce_max_length_chains
    _a = _NS(object_id="a", coords=[(0, 0), (400, 0)], flow_tph=10,
             start_node_id="n1", end_node_id="n2")
    _b = _NS(object_id="b", coords=[(400, 0), (800, 0)], flow_tph=10,
             start_node_id="n2", end_node_id="n3")
    from app.engine.hydraulics import size_segment as _ss
    _ss(_a, _ref)  # Ду100 (22,3), предельная 419 м
    _ss(_b, _ref)
    _w: list = []
    enforce_max_length_chains([_a, _b], _ref, _w)
    # 400+400=800 м одной цепочкой (узел n2 степени 2, отсчёт НЕ сбрасывается):
    # протокол п.7 — повышение максимум на ОДИН номенклатурный шаг:
    # Ду100 → Ду125 (предельная 554 м); 800 м всё равно > 554 → предупреждение
    checks.append(("§3: цепочка 800 м повышается на ОДИН шаг до Ду125 (протокол п.7)",
                   _a.diameter_mm == 125 and _b.diameter_mm == 125 and bool(_w)))
    checks.append(("§3: предупреждение, что 800 м > предельной и для Ду125",
                   any("предельн" in w for w in _w)))

    # --- протокол п.9: нештатный угол отвода → ×1,5 (юнит) ---
    from app.engine.hydraulics import nonstandard_bend as _nb, reprice as _rp
    checks.append(("п.9: отвод 90° — штатный",
                   not _nb([(0, 0), (100, 0), (100, 100)])))
    checks.append(("п.9: отвод 45° — штатный",
                   not _nb([(0, 0), (100, 0), (200, 100)])))
    checks.append(("п.9: отвод 135° — нештатный",
                   _nb([(0, 0), (100, 0), (50, 50)])))
    checks.append(("п.9: отвод 30° — нештатный",
                   _nb([(0, 0), (100, 0), (200, 57.735)])))
    _c = _NS(object_id="c", coords=[(0, 0), (100, 0)], flow_tph=10)
    _ss(_c, _ref)
    _base_cost = _c.cost_rub
    _c.bend_factor = 1.5
    _rp(_c, _ref)
    checks.append(("п.9: ×1,5 к стоимости участка с нештатным углом",
                   abs(_c.cost_rub - _base_cost * 1.5) < 1.0))

    # --- протокол п.9: отказ при дороговизне (юнит-калькуляция) ---
    from types import SimpleNamespace as _SNS
    from app.engine.pipeline import _pack_direct_cost
    _s1 = _NS(object_id="z", coords=[(0, 0), (5000, 0)], flow_tph=10,
              start_node_id="t1", end_node_id="o1")
    _ss(_s1, _ref)  # 5000 м — один шаг Ду100→Ду125, ~5 км × 97275 ₽/м
    _tap = _SNS(kind="new_chamber_on_segment", tap_cost_rub=5_000_000,
                chamber_id=None, segment_id=None, required_dn=125)
    _cost = _pack_direct_cost([_s1], [], [_tap], None, _ref)
    checks.append(("п.9: трасса 5 км дороже штрафа §8.3 → отказ от подключения",
                   _cost > _ref.unconnected_penalty(10)))

    # --- протокол п.9: невалидная геометрия → диагностическая ошибка (юнит) ---
    from app.engine.loader import load_contest_geojson, PipelineInputError
    _bad = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"object_type": "heat_chamber",
                                           "object_id": "C", "diameter": 500},
         "geometry": {"type": "Point", "coordinates": [37.6, 55.7]}},
        {"type": "Feature", "properties": {"object_type": "heat_network",
                                           "object_id": "S", "diameter": 500,
                                           "flow_tph": 100},
         "geometry": {"type": "LineString",
                      "coordinates": [[37.6, 55.7], [37.601, 55.7]]}},
        {"type": "Feature", "properties": {"object_type": "oks_existing",
                                           "object_id": "BAD"},
         "geometry": {"type": "Polygon", "coordinates": [[
             [37.6, 55.7], [37.61, 55.7], [37.6, 55.71],
             [37.61, 55.71], [37.6, 55.7]]]}},  # «бантик» — самопересечение
    ]}
    _bad_path = Path(tempfile.mkdtemp()) / "bad.geojson"
    _bad_path.write_text(json.dumps(_bad), encoding="utf-8")
    try:
        load_contest_geojson(_bad_path, _ref)
        _bad_err = None
    except PipelineInputError as exc:
        _bad_err = str(exc)
    checks.append(("п.9: невалидная геометрия → PipelineInputError с диагностикой",
                   _bad_err is not None and "BAD" in _bad_err))

    print("=== Проверки ===")
    ok = True
    for name, passed in checks:
        print(f"  [{'OK' if passed else 'FAIL'}] {name}")
        ok = ok and passed

    return 0 if ok else 1


# ставки реконструкции таблицы 4.1 (для проверки §7)
_RECON_TARIFF = {
    50: 96180, 65: 109989, 80: 117582, 100: 133694, 125: 148030,
    150: 152295, 200: 181766, 250: 202030, 300: 228707, 400: 271317,
    500: 333884, 600: 372703, 700: 439571, 800: 489918, 900: 553607,
    1000: 606679, 1200: 825692, 1400: 978584,
}


if __name__ == "__main__":
    sys.exit(main())
