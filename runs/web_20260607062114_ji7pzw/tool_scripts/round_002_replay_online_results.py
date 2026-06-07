# Auto-generated project-local analysis script.
# It must run inside the repository and should not access paths outside it.

from __future__ import annotations

import json
from pathlib import Path

root = Path.cwd()
files = sorted((root / "evaluations").glob("online_result_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:8]
print(f"recent_online_results={len(files)}")
previous = None
for path in reversed(files):
    data = json.loads(path.read_text(encoding="utf-8"))
    avg = float(data.get("avg_score") or 0.0)
    delta = "" if previous is None else f" delta={avg - previous:+.2f}"
    print(f"\n{path.name}: avg={avg:.2f}{delta} success={data.get('success_count')}/{data.get('case_count')}")
    previous = avg
    for case in data.get("case_results", []):
        details = case.get("detail") or []
        multi = sum(1 for d in details if len(d.get("couriers") or []) > 1)
        bundles = sum(1 for d in details if "," in str(d.get("task_id_list") or ""))
        print(
            f"  {case.get('case_file')}: score={float(case.get('total_score') or 0.0):.2f} "
            f"assigned={case.get('assigned_count')} unassigned={case.get('unassigned_count')} "
            f"multi={multi} bundles={bundles}"
        )
