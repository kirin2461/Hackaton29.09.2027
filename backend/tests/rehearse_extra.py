#!/usr/bin/env python3
"""Репетиция на дополнительном наборе (§2.14): run внутри geo-engine.

Проверки по техприложению ЛЦТ-2026:
  §2.9/§8.3 — E5 внутри запрещённой территории: unconnected,
              штраф 100 млн + 500 тыс. × 10 = 105 млн ₽;
  §7        — E4 (200 т/ч) врезан в середину R1: ЧАСТИЧНАЯ реконструкция
              R1 (Ду300 → Ду400), R2 НЕ реконструируется (240 ≤ 274,9);
  §8.2      — реконструкция камеры RC1 (Ду300 → Ду400, 5 млн ₽);
  §10       — строгий контракт выходного GeoJSON (семь типов).
"""
import json
import sys
import tempfile
from pathlib import Path

BACKEND = Path("/srv")
if not (BACKEND / "app" / "engine").exists():
    BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from tests.make_contest_sample_extra import OUT, main as make_extra  # noqa: E402
from app.engine.pipeline import run_pipeline  # noqa: E402
from tests.run_engine_smoke import CONTRACT, contract_checks  # noqa: E402

if not OUT.exists():
    make_extra()

result_path = Path(tempfile.mkdtemp()) / "result_extra.geojson"
summary = run_pipeline(OUT, result_path)
data = json.loads(result_path.read_text(encoding="utf-8"))

print("engine:", summary["engine"])
print("ОКС подключено: {}/{}".format(summary["buildings_connected"], summary["buildings_total"]))
print("unconnected:", summary["unconnected_ids"])
print("стоимость (рекомендуемый): {:.1f} млн ₽".format(summary["costs_rub"]["total"] / 1e6))
for v in summary["variants"]:
    print("  #{} {}: score={:.4f}, {:.1f} млн ₽, {:.0f} м, статус {}".format(
        v["rank"], v["label"], v["score"], v["costs_rub"]["total"] / 1e6,
        v["length_total_m"], v["status"]))

by_type = {}
for f in data["features"]:
    by_type.setdefault(f["properties"]["object_type"], []).append(f["properties"])

recon = by_type.get("heat_network_reconstruction", [])
recon_ids = {r["existing_object_id"] for r in recon}
summaries = by_type.get("variant_summary", [])

checks = []
checks.append(("§2.9: E5 в unconnected (запрещённая территория)",
               "E5" in summary["unconnected_ids"]))
checks.append(("остальные ОКС подключены (4 из 5)",
               summary["buildings_connected"] == 4))
checks.append(("§8.3: штраф за E5 (10 т/ч) = 105 млн ₽ в каждом варианте",
               bool(summaries) and all(
                   s["unconnected_penalty"] == 105_000_000
                   and s["unconnected_oks_ids"] == ["E5"] for s in summaries)))
checks.append(("§7: R1 реконструируется ЧАСТИЧНО (Ду300 → Ду500)",
               "R1" in recon_ids and all(
                   r["required_diameter"] == 400 and r["existing_diameter"] == 300
                   for r in recon if r["existing_object_id"] == "R1")))
_r1_full = 249.2  # длина R1 ≈ 0,004° × 62,3 км
checks.append(("§7: реконструкция R1 короче полного участка (от врезки к источнику)",
               any(r["existing_object_id"] == "R1" and r["length"] < _r1_full - 5
                   for r in recon)))
checks.append(("§7: R2 НЕ реконструируется (180+60=240 ≤ 274,9)",
               "R2" not in recon_ids))
checks.append(("§7: R0 не реконструируется (1100+260=1360 ≤ 2627,7)",
               "R0" not in recon_ids))
checks.append(("§7: ставка по требуемому Ду (без Kспец/Kгл)",
               all(abs(r["cost"] - r["length"] * 271317) < 1.0
                   for r in recon if r["existing_object_id"] == "R1")))
recon_ch = by_type.get("heat_chamber_reconstruction", [])
checks.append(("§8.2: реконструкция камеры RC1 (Ду300 → Ду400, 5 млн ₽)",
               any(c["existing_object_id"] == "RC1"
                   and c["required_diameter"] == 400
                   and c["cost"] == 5000000 for c in recon_ch)))
ties = by_type.get("tie_in", [])
checks.append(("§8.2: каждая врезка 5 млн ₽",
               bool(ties) and all(t["cost"] == 5000000 for t in ties)))
checks.append(("§5.1: спецпроход по дороге K=1,60 (трасса к E4)",
               any(s["laying_method"] == "special"
                   for s in by_type.get("heat_network", []))))
checks.append(("вариантов >= 2", len(summary["variants"]) >= 2))
checks.append(("§9: score соответствует формуле",
               all(abs(s["score"] - (0.7 * s["calculated_cost"] / 25e6
                                     + 0.3 * s["length"] / 100)) < 0.01
                   for s in summaries)))
checks.extend(contract_checks(data))

print("=== Репетиция ===")
ok = True
for name, passed in checks:
    print("  [{}] {}".format("OK" if passed else "FAIL", name))
    ok = ok and passed
sys.exit(0 if ok else 1)
