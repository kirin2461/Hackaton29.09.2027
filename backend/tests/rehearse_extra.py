#!/usr/bin/env python3
"""Репетиция на дополнительном наборе (§2.14): run внутри geo-engine."""
import json, sys, tempfile
from pathlib import Path

BACKEND = Path("/srv")
sys.path.insert(0, str(BACKEND))

from tests.make_contest_sample_extra import OUT, main as make_extra
from app.engine.pipeline import run_pipeline

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

checks = []
checks.append(("E5 в unconnected (запретная зона)", "E5" in summary["unconnected_ids"]))
checks.append(("остальные ОКС подключены", summary["buildings_connected"] == 4))
recon = [f for f in data["features"] if f["properties"]["object_type"] == "reconstruction_segment"]
recon_ids = {f["properties"]["object_id"] for f in recon}
checks.append(("реконструкция R1 и R2 (крупный E4)", {"R1", "R2"} <= recon_ids))
checks.append(("вариантов >= 2", len(summary["variants"]) >= 2))
unc = [f for f in data["features"] if f["properties"]["object_type"] == "unconnected"]
checks.append(("у unconnected есть причина", bool(unc) and all(f["properties"].get("reason") for f in unc)))
print("=== Репетиция ===")
ok = True
for name, passed in checks:
    print("  [{}] {}".format("OK" if passed else "FAIL", name))
    ok = ok and passed
sys.exit(0 if ok else 1)
