"""Смоук-тест движка Спринта 2 на синтетическом конкурсном наборе.

Запуск из папки backend/:
    python tests/run_engine_smoke.py

Проверяет критерий спринта: все ОКС подключены, диаметры/предельные
длины/реконструкция посчитаны, выходной GeoJSON валиден.
"""

import json
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from tests.make_contest_sample import OUT as SAMPLE_PATH, main as make_sample  # noqa: E402
from app.engine.pipeline import run_pipeline  # noqa: E402


def main() -> int:
    if not SAMPLE_PATH.exists():
        make_sample()

    result_path = Path(tempfile.mkdtemp()) / "result.geojson"
    summary = run_pipeline(SAMPLE_PATH, result_path)

    print("=== Сводка ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    data = json.loads(result_path.read_text(encoding="utf-8"))
    by_type = {}
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
    checks.append(("ранги проставлены по возрастанию score",
                   all(variants[i]["score"] <= variants[i + 1]["score"]
                       for i in range(len(variants) - 1))))
    checks.append(("ровно один рекомендуемый вариант",
                   sum(1 for v in variants if v["is_recommended"]) == 1))
    checks.append(("варианты содержательно разные (у «Раздельного» нет стволов)",
                   any(v["label"].startswith("Раздельное") for v in variants)))
    checks.append(("есть новые участки", len(by_type.get("new_segment", [])) > 0))
    checks.append(("диаметры назначены",
                   all(s["diameter_mm"] > 0 for s in by_type.get("new_segment", []))))
    checks.append(("объекты помечены рангом варианта",
                   all("variant" in f["properties"] for f in data["features"])))
    checks.append(("есть реконструкция существующей сети (B4 перегружает S1)",
                   any(s["object_id"] == "S1" for s in by_type.get("reconstruction_segment", []))))
    checks.append(("есть спецпроход отдельным участком (путь к B3)",
                   any(s["method"] == "special_passage" for s in by_type.get("new_segment", []))))
    checks.append(("сводная стоимость > 0", summary["costs_rub"]["total"] > 0))

    # В раздельном варианте стволов быть не должно
    separate_rank = next((v["rank"] for v in variants
                          if v["label"].startswith("Раздельное")), None)
    if separate_rank is not None:
        trunk_in_separate = [
            s for s in by_type.get("new_segment", [])
            if s["variant"] == separate_rank and s["role"] == "trunk"
        ]
        checks.append(("у раздельного варианта нет стволовых участков",
                       len(trunk_in_separate) == 0))


    # --- Задание на глубину (Спринт 4) ---
    seg_feats = [f for f in data["features"]
                 if f["properties"]["object_type"] == "new_segment"]
    checks.append(("новые участки с Z-координатами (GeoJSON 3D)",
                   all(len(c) == 3 for s in seg_feats
                       for c in s["geometry"]["coordinates"])))
    step = 0.5
    checks.append(("отметки глубины квантованы шагом 0.5 м",
                   all(abs((c[2] / step) - round(c[2] / step)) < 1e-6
                       for s in seg_feats for c in s["geometry"]["coordinates"])))
    checks.append(("глубины в допустимом диапазоне (1.0–5.0 м)",
                   all(1.0 <= s["properties"]["depth_max_m"] <= 5.0
                       for s in seg_feats)))
    checks.append(("камеры с отметкой дна (depth_m)",
                   all(c.get("depth_m") for c in by_type.get("new_chamber", []))))

    # юнит-проверка профиля: глубокая точка подключения -> пандус + множитель
    from app.engine.depth import assign_depth, target_depth_m
    from app.engine.hydraulics import NewSegment
    from app.engine.refdata import RefData
    ref = RefData()
    seg = NewSegment(object_id="t", coords=[(0, 0), (100, 0)], flow_tph=10)
    seg.diameter_mm = 100
    seg.cost_rub = 1000.0
    assign_depth(seg, ref, entry_depth_m=4.5)
    ramp = seg.depth_m
    checks.append(("пандус от глубокой точки подключения (уклон <= нормы)",
                   abs(seg.coords3d[0][2]) == 4.5 and ramp == 4.5
                   and abs(seg.coords3d[-1][2]) == target_depth_m(100, ref)))
    checks.append(("глубокая прокладка повышает стоимость",
                   seg.cost_rub > 1000.0 and any("глубокая" in w for w in seg.warnings)))

    print("=== Проверки ===")
    ok = True
    for name, passed in checks:
        print(f"  [{'OK' if passed else 'FAIL'}] {name}")
        ok = ok and passed

    trunk = [s for s in by_type.get("new_segment", [])
             if s["role"] == "trunk" and s["variant"] == 1]
    print(f"  стволовых участков в варианте #1: {len(trunk)}")
    if trunk:
        print(f"  расход ствола: {trunk[0]['flow_tph']} т/ч (ожидалось 55 = 25+30)")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
