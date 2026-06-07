"""Evaluate V1-V7 using calibrated data and corrected protocol (DetCov-first)."""
import sys, os, json, importlib.util

sys.path.insert(0, os.path.dirname(__file__))
from data_generator import generate, CALIBRATED_PRESETS
from parser import parse
from judge import evaluate_deterministic, evaluate_monte_carlo

def load_solver(path):
    spec = importlib.util.spec_from_file_location('solver', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.solve

SOLVERS = {
    "V2_BucketedWilling": load_solver("snapshots/solver_bucketedwillingness_v2_20260514_195438.py"),
    "V3_AdaptiveHybrid": load_solver("snapshots/solver_adaptivehybrid_v3_20260514_204511.py"),
    "V4_UnifiedTwoPhase": load_solver("snapshots/solver_unified_v4_20260514_221447.py"),
    "V5_HybridScarceNorm": load_solver("snapshots/solver_hybrid_v5_20260514_223508.py"),
    "V6_Adaptive": load_solver("snapshots/solver_adaptive_v6_20260515_101252.py"),
    "V7_AdaptiveBackup": load_solver("snapshots/solver_adaptive_v7_20260515_114527.py"),
}

def v1_greedy_willingness(input_text):
    lines = input_text.strip().splitlines()
    if not lines:
        return []
    start = 1 if lines[0].startswith("task_id_list") else 0
    candidates = []
    for line in lines[start:]:
        parts = line.strip().split("\t")
        if len(parts) < 4:
            continue
        try:
            willingness = float(parts[3])
        except ValueError:
            continue
        if willingness <= 0:
            continue
        task_ids = tuple(t.strip() for t in parts[0].split(",") if t.strip())
        if not task_ids:
            continue
        try:
            score = float(parts[2])
        except ValueError:
            score = float("inf")
        candidates.append((task_ids, parts[1].strip(), score, willingness))
    candidates.sort(key=lambda x: -x[3])
    assigned_couriers = set()
    assigned_tasks = set()
    result = []
    for task_ids, courier_id, score, willingness in candidates:
        if courier_id in assigned_couriers:
            continue
        if any(t in assigned_tasks for t in task_ids):
            continue
        assigned_couriers.add(courier_id)
        assigned_tasks.update(task_ids)
        result.append((",".join(task_ids), [courier_id]))
    return result

SOLVERS["V1_GreedyWill"] = v1_greedy_willingness

PRESETS_TO_USE = [
    "calibrated_tiny", "calibrated_small", "calibrated_medium", "calibrated_large",
    "calibrated_scarce", "calibrated_low_will", "calibrated_high_noise",
]

ONLINE_TARGETS = {"tiny": 210, "small": 452, "medium": 867, "large": 1076,
                  "scarce": 1795, "low_will": 2298, "high_noise": 903}

print("=" * 125)
print("VERSION COMPARISON -- Calibrated Data + Corrected Protocol (DetCov-first)")
print("=" * 125)
print("Rule: DetCov must = 1.0 | Minimize DetScore | MC is secondary")
print()

# Generate data once
datasets = {}
for name in PRESETS_TO_USE:
    params = CALIBRATED_PRESETS[name]["params"].copy()
    params["seed"] = hash(name) % 10000
    datasets[name] = generate(**params)

# Evaluate
all_results = {}
for solver_name, solver_fn in SOLVERS.items():
    all_results[solver_name] = {}
    for ds_name, text in datasets.items():
        data = parse(text)
        plan = solver_fn(text)
        det = evaluate_deterministic(plan, data)
        mc = evaluate_monte_carlo(plan, data, n_simulations=300, seed=42)
        all_results[solver_name][ds_name] = {
            "det_cov": round(det.coverage_rate, 3),
            "det_score": round(det.total_score, 1),
            "mc_cov": round(mc.coverage_rate, 3),
            "mc_score": round(mc.total_score, 1),
            "est_pen": round(mc.estimated_penalty, 1),
            "entries": len(plan),
        }

# Table per dataset
for ds_name in PRESETS_TO_USE:
    short = ds_name.replace("calibrated_", "")
    online = ONLINE_TARGETS.get(short, 0)

    print("-" * 125)
    print(f"Dataset: {ds_name} (online V6 target: {online})")
    print(f"  {'Version':<22} | {'DetCov':>7} {'DetScore':>9} | {'Entries':>7} | {'MCov':>6} {'EstPen':>9} | vsV6_Det | vsOnline")
    print(f"  {'-'*22} | {'-'*7} {'-'*9} | {'-'*7} | {'-'*6} {'-'*9} | {'-'*8} | {'-'*7}")

    v6_det = all_results["V6_Adaptive"][ds_name]["det_score"]
    ranked = sorted(all_results.items(),
                    key=lambda x: (-x[1][ds_name]["det_cov"], x[1][ds_name]["det_score"]))

    for solver_name, _ in ranked:
        r = all_results[solver_name][ds_name]
        cov_str = "PASS" if r["det_cov"] >= 1.0 else "FAIL"
        det_delta = r["det_score"] - v6_det
        online_delta = r["det_score"] - online
        print(f"  {solver_name:<22} | {cov_str:>7} {r['det_score']:>9.1f} | {r['entries']:>7} | {r['mc_cov']:>6.3f} {r['est_pen']:>9.1f} | {det_delta:+8.1f} | {online_delta:+7.0f}")
    print()

# Summary
print("=" * 125)
print("SUMMARY: Average DetScore across all 7 calibrated presets (lower = better)")
print("=" * 125)
print(f"  {'Version':<22} | {'AvgDetSc':>9} | {'CovOK':>6} | {'AvgEnt':>7} | {'AvgEstPen':>10} | {'Rank':>4}")
print(f"  {'-'*22} | {'-'*9} | {'-'*6} | {'-'*7} | {'-'*10} | {'-'*4}")

summary = {}
for solver_name in SOLVERS:
    det_scores, est_pens, entries, covs = [], [], [], []
    for ds_name in PRESETS_TO_USE:
        r = all_results[solver_name][ds_name]
        det_scores.append(r["det_score"])
        est_pens.append(r["est_pen"])
        entries.append(r["entries"])
        covs.append(r["det_cov"])
    n_cov_ok = sum(1 for c in covs if c >= 1.0)
    summary[solver_name] = {
        "avg_det": sum(det_scores) / len(det_scores),
        "cov_ok": n_cov_ok,
        "avg_ent": sum(entries) / len(entries),
        "avg_est": sum(est_pens) / len(est_pens),
    }

# Rank by: CovOK desc, AvgDetScore asc
ranked = sorted(summary.items(),
                key=lambda x: (-x[1]["cov_ok"], x[1]["avg_det"]))
for rank, (name, s) in enumerate(ranked, 1):
    print(f"  {name:<22} | {s['avg_det']:>9.1f} | {s['cov_ok']:>4}/7 | {s['avg_ent']:>7.1f} | {s['avg_est']:>10.1f} | {rank:>4}")

# Print best
print()
for name, s in ranked:
    if s["cov_ok"] == 7:
        v6_name = "V6_Adaptive"
        v6_s = summary[v6_name]
        delta = s["avg_det"] - v6_s["avg_det"]
        flag = " <<< BEST" if delta <= 0 else " (worse than V6)"
        print(f"  {name}: DetCov 7/7, AvgDetSc={s['avg_det']:.1f}, vs V6: {delta:+.1f}{flag}")

print()
print("CONCLUSION:")
full_cov = [n for n, s in ranked if s["cov_ok"] == 7]
if full_cov:
    best = min(full_cov, key=lambda n: summary[n]["avg_det"])
    print(f"  Best: {best} (7/7 DetCov, lowest AvgDetSc={summary[best]['avg_det']:.1f})")
else:
    print(f"  No solver achieves DetCov=1.0 on all presets")

# V6 vs V7 comparison
v6_s = summary["V6_Adaptive"]
v7_s = summary["V7_AdaptiveBackup"]
print(f"  V6 -> V7 Delta: AvgDetSc {v7_s['avg_det'] - v6_s['avg_det']:+.1f}, "
      f"AvgEntries {v7_s['avg_ent'] - v6_s['avg_ent']:+.1f}")
if v7_s["avg_det"] > v6_s["avg_det"]:
    print("  V7 would have been REJECTED under corrected protocol (DetScore increased)")

# Save results
output = {
    "protocol": "DetCov first (must = 1.0), minimize DetScore, MC secondary",
    "data": "calibrated presets matching V6 online DetScore",
    "per_dataset": {},
    "summary": {k: {kk: round(vv, 1) for kk, vv in v.items()} for k, v in summary.items()},
}
for ds_name in PRESETS_TO_USE:
    output["per_dataset"][ds_name] = {}
    for solver_name in SOLVERS:
        output["per_dataset"][ds_name][solver_name] = all_results[solver_name][ds_name]

with open("evaluations/version_comparison_calibrated.json", "w") as f:
    json.dump(output, f, indent=2)
print(f"\nResults saved to evaluations/version_comparison_calibrated.json")
