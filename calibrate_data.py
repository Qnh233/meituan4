"""Calibrate data generator to match online V6 results.

Key insight: online 'completion_rate' = deterministic coverage (all tasks assigned).
Penalty = total_score of ALL assigned couriers (not just accepted ones).
This means: minimize DetScore while keeping DetCov = 1.0.
MC simulation is secondary — for robustness checking only.

Calibration target: local DetScore roughly matches online penalty.
"""

import sys, os, json
sys.path.insert(0, os.path.dirname(__file__))
from data_generator import generate, PRESETS
from parser import parse
from judge import evaluate_deterministic, evaluate_monte_carlo
from solver import solve as v6_solve


def analyze(name, params, seed=42):
    p = params.copy()
    p["seed"] = seed
    text = generate(**p)
    data = parse(text)
    plan = v6_solve(text)
    det = evaluate_deterministic(plan, data)
    mc = evaluate_monte_carlo(plan, data, n_simulations=300, seed=42)
    wills = [c.willingness for c in data.candidates]
    return {
        "n_tasks": len(data.all_tasks),
        "n_couriers": len(data.all_couriers),
        "mean_w": round(sum(wills)/len(wills), 4),
        "median_w": round(sorted(wills)[len(wills)//2], 4),
        "det_cov": round(det.coverage_rate, 3),
        "det_score": round(det.total_score, 1),
        "mc_cov": round(mc.coverage_rate, 3),
        "mc_score": round(mc.total_score, 1),
        "est_pen": round(mc.estimated_penalty, 1),
        "entries": len(plan),
    }


ONLINE_TARGETS = {
    "tiny": 210,
    "small": 452,
    "medium": 867,
    "large": 1076,
    "scarce_couriers": 1795,
    "low_willingness": 2298,
    "high_noise": 903,
}

# ── Sweep for each preset to find params that match online DetScore ──

def sweep_preset(name, target_score):
    """Find willingness and score params where V6 DetScore ≈ target."""
    orig = PRESETS[name]["params"].copy()

    base = {
        "n_tasks": orig["n_tasks"],
        "n_couriers": orig["n_couriers"],
        "candidates_per_task": orig["candidates_per_task"],
        "combined_ratio": orig.get("combined_ratio", 0.9),
        "max_combined": orig.get("max_combined", 2),
        "score_will_corr": orig.get("score_will_corr", 0.0),
    }

    best = None
    best_gap = float("inf")

    # Sweep score ranges and willingness parameters
    score_ranges = [
        (10, 80), (15, 100), (20, 120), (30, 150), (40, 180),
        (50, 200), (10, 60), (5, 50),
    ]
    will_params = [
        (2.5, 2.0),   # mean=0.56
        (2.0, 2.5),   # mean=0.44
        (3.0, 2.0),   # mean=0.60
        (2.0, 3.0),   # mean=0.40
        (1.8, 3.5),   # mean=0.34
        (1.5, 3.0),   # mean=0.33
        (1.3, 4.0),   # mean=0.245 (low_will path)
    ]

    for s_min, s_max in score_ranges:
        for w_alpha, w_beta in will_params:
            params = base.copy()
            params["score_min"] = s_min
            params["score_max"] = s_max
            params["willingness_alpha"] = w_alpha
            params["willingness_beta"] = w_beta

            r = analyze(name, params)
            gap = abs(r["det_score"] - target_score)

            # Prefer det_cov=1.0 and det_score close to target
            if r["det_cov"] >= 1.0 and gap < best_gap:
                best_gap = gap
                best = {"params": params, "result": r, "gap": r["det_score"] - target_score}

    return best


print("Sweeping parameters to match V6 online DetScore...")
print()

calibrated = {}
for name in ONLINE_TARGETS:
    target = ONLINE_TARGETS[name]
    print(f"  {name}: target={target}...", end=" ", flush=True)
    best = sweep_preset(name, target)
    if best:
        r = best["result"]
        calibrated[name] = best["params"]
        print(f"best DetSc={r['det_score']:.0f} (gap={best['gap']:+.0f}), "
              f"score=[{best['params']['score_min']},{best['params']['score_max']}], "
              f"will=({best['params']['willingness_alpha']},{best['params']['willingness_beta']}), "
              f"mean_w={r['mean_w']:.3f}")
    else:
        print("no valid solution!")

# ── Test all calibrated params ──
print()
print("=" * 120)
print("FULL TEST WITH CALIBRATED PARAMS")
print("=" * 120)
header = f"{'Preset':<20} | {'nT':>3} {'nC':>3} | {'mean_w':>7} {'med_w':>7} | {'DetCov':>6} {'DetSc':>8} | {'MCCov':>6} {'MCSc':>8} | {'EstPen':>9} | {'Online':>8} | DetGap | DetCovOK"
print(header)
print("-" * 120)

results = {}
total_det_gap = 0
for name in ONLINE_TARGETS:
    r = analyze(name, calibrated[name])
    results[name] = r
    online = ONLINE_TARGETS[name]
    det_gap = r["det_score"] - online
    total_det_gap += abs(det_gap)
    cov_ok = "Y" if r["det_cov"] >= 1.0 else "N"
    print(f"{name:<20} | {r['n_tasks']:>3} {r['n_couriers']:>3} | "
          f"{r['mean_w']:>7.4f} {r['median_w']:>7.4f} | "
          f"{r['det_cov']:>6.3f} {r['det_score']:>8.1f} | "
          f"{r['mc_cov']:>6.3f} {r['mc_score']:>8.1f} | "
          f"{r['est_pen']:>9.1f} | {online:>8} | {det_gap:+7.0f} | {cov_ok}")

print("-" * 120)
print(f"AVG |DetGap|: {total_det_gap/len(ONLINE_TARGETS):.0f}")

# Save calibrated presets
calib_data = {
    "description": "Calibrated data generator params — DetScore matches V6 online penalty",
    "note": "Uses DETERMINISTIC score as primary metric. Online 'completion' = deterministic coverage.",
    "targets": ONLINE_TARGETS,
    "results": {k: {"det_score": v["det_score"], "det_gap": round(v["det_score"] - ONLINE_TARGETS[k], 1),
                     "det_cov": v["det_cov"], "mean_w": v["mean_w"]} for k, v in results.items()},
    "params": calibrated,
}
with open("evaluations/calibrated_params.json", "w") as f:
    json.dump(calib_data, f, indent=2)
print("\nSaved to evaluations/calibrated_params.json")
