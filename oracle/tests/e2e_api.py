#!/usr/bin/env python3
"""E2E через Java API: загрузка датасета -> опрос -> результат -> проверка §10.

Запуск из контейнера geo-engine (сеть docker):
    python3 tests/e2e_api.py
или с хоста (порт 8080 опубликован):
    APP_URL=http://localhost:8080 python3 tests/e2e_api.py
"""
import json, os, sys, time, uuid, urllib.request
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS))
from run_engine_smoke import contract_checks  # проверки контракта §10

BASE = os.environ.get("APP_URL", "http://app:8080")

def post_file(path):
    boundary = uuid.uuid4().hex
    payload = Path(path).read_bytes()
    name = Path(path).name
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{name}"\r\n'
        f"Content-Type: application/geo+json\r\n\r\n"
    ).encode() + payload + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        BASE + "/api/jobs", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode())

def get(path):
    with urllib.request.urlopen(BASE + path, timeout=60) as r:
        return json.loads(r.read().decode())

def run_case(path):
    print(f"\n=== {path} ===")
    job = post_file(path)
    jid = job.get("id") or job.get("job_id")
    print("job:", jid, "status:", job.get("status"))
    for _ in range(120):
        time.sleep(3)
        st = get(f"/api/jobs/{jid}")
        status = str(st.get("status", "")).lower()
        if status in ("done", "completed", "success"):
            break
        if status in ("failed", "error"):
            print("FAILED:", st)
            return False
    else:
        print("TIMEOUT waiting for job")
        return False
    res = get(f"/api/jobs/{jid}/result")
    out = Path(path).with_name("e2e_result_" + Path(path).name)
    out.write_text(json.dumps(res, ensure_ascii=False))
    print("result ->", out, "features:", len(res.get("features", [])))
    problems = [name for name, ok in contract_checks(res) if not ok]
    summaries = [f for f in res["features"]
                 if f["properties"].get("object_type") == "variant_summary"]
    for s in sorted(summaries, key=lambda s: s["properties"]["rank"]):
        p = s["properties"]
        print(f"  variant {p['variant_id']}: rank={p['rank']} "
              f"cost={p['calculated_cost']:.0f} len={p['length']:.1f} "
              f"score={p['score']:.4f} unconnected={p.get('unconnected_oks_ids')}")
    if problems:
        print("CONTRACT FAIL:")
        for pr in problems:
            print("  -", pr)
        return False
    print("CONTRACT OK")
    return True

ok = True
for ds in (TESTS / "data" / "contest_sample.geojson",
           TESTS / "data" / "contest_sample_extra.geojson"):
    ok = run_case(str(ds)) and ok
print("\nE2E:", "ALL OK" if ok else "FAILED")
sys.exit(0 if ok else 1)
