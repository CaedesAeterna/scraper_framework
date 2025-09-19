#!/usr/bin/env python3
"""
Small utility to pretty-print summary tables from results.json
"""
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results" / "results.json"

if not RESULTS.exists():
    raise SystemExit(f"Missing results file: {RESULTS}")

with open(RESULTS, "r", encoding="utf-8") as f:
    data = json.load(f)

rows = []
for r in data:
    m = r.get("metrics", {})
    rows.append({
        "target": r.get("target"),
        "method": r.get("method"),
        "ok": r.get("ok"),
        "accuracy": round(m.get("accuracy", 0), 1),
        "completeness": round(m.get("completeness", 0), 1),
        "freshness": round(m.get("freshness", 0), 1),
        "redundancy": round(m.get("redundancy", 0), 1),
        "throughput": round(m.get("throughput", 0), 1),
        "robustness": round(m.get("robustness", 0), 1),
    })

print(pd.DataFrame(rows).to_string(index=False))
