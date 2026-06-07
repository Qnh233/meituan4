"""Test V8 vs V6 on calibrated data + corrected protocol."""
import sys, os, json, importlib.util

sys.path.insert(0, os.path.dirname(__file__))
from data_generator import generate, CALIBRATED_PRESETS
from parser import parse
from judge import evaluate_deterministic, evaluate_monte_carlo

# Load V6 and V8
spec6 = importlib.util.spec_from_file_location('v6', 'snapshots/solver_adaptive_v6_20260515_101252.py')
v6_mod = importlib.util.module_from_spec(spec6)
spec6.loader.exec_module(v6_mod)
v6_solve = v6_mod.solve

from solver import solve as v8_solve

PRESETS = [
    "calibrated_tiny", "calibrated_small", "calibrated_medium", "calibrated_large",
    "calibrated_scarce", "calibrated_low_will", "calibrated_high_noise",
]
ONLINE = {"tiny": 210, "small": 452, "medium": 867, "large": 1076,
          "scarce": 1795, "low_will": 2298, "high_noise": 903}

print("=" * 130)
print("V8 vs V6 COMPARISON (calibrated data, DetCov-first protocol)")
print("=" * 130)
print("V8: scarce=V6(set cover) | low_will=V6(bucket+ratio) | normal=GreedyRatio(w/s desc)")
print()

datasets = {}
for name in PRESETS:
    params = CALIBRATED_PRESETS[name]["params"].copy()
    params["seed"] = hash(name) % 10000
    datasets[name] = generate(**params)

print(f"{'Dataset':<22} | {'Ver':<4} | {'DetCov':>7} {'DetSc':>9} | {'MCov':>6} {'MCSc':>8} {'EstPen':>9} | {'Ent':>4} | vsV6_Det")
print("-" * 130)

v6_sum, v8_sum = 0, 0
v6_covs, v8_covs = 0, 0
all_rows = []

for ds_name in PRESETS:
    short = ds_name.replace("calibrated_", "")
    online = ONLINE[short]
    data = parse(datasets[ds_name])

    p6 = v6_solve(datasets[ds_name])
    p8 = v8_solve(datasets[ds_name])

    d6 = evaluate_deterministic(p6, data)
    d8 = evaluate_deterministic(p8, data)
    m6 = evaluate_monte_carlo(p6, data, n_simulations=300, seed=42)
    m8 = evaluate_monte_carlo(p8, data, n_simulations=300, seed=42)

    v6_sum += d6.total_score
    v8_sum += d8.total_score
    if d6.coverage_rate >= 1.0: v6_covs += 1
    if d8.coverage_rate >= 1.0: v8_covs += 1

    delta = d8.total_score - d6.total_score
    flag = " >> BETTER" if delta < -5 else (" >> WORSE" if delta > 5 else "")

    def cov_str(c): return "PASS" if c >= 1.0 else "FAIL"
    print(f"{short:<22} | V6  | {cov_str(d6.coverage_rate):>7} {d6.total_score:>9.1f} | {m6.coverage_rate:>6.3f} {m6.total_score:>8.1f} {m6.estimated_penalty:>9.1f} | {len(p6):>4} |")
    print(f"{'':<22} | V8  | {cov_str(d8.coverage_rate):>7} {d8.total_score:>9.1f} | {m8.coverage_rate:>6.3f} {m8.total_score:>8.1f} {m8.estimated_penalty:>9.1f} | {len(p8):>4} | {delta:+8.1f}{flag}")
    print()

print("=" * 130)
print(f"SUMMARY")
print(f"  V6: AvgDetSc={v6_sum/len(PRESETS):.1f}, DetCovOK={v6_covs}/{len(PRESETS)}")
print(f"  V8: AvgDetSc={v8_sum/len(PRESETS):.1f}, DetCovOK={v8_covs}/{len(PRESETS)}")
delta_avg = (v8_sum - v6_sum) / len(PRESETS)
print(f"  Delta: {delta_avg:+.1f} ({delta_avg/(v6_sum/len(PRESETS))*100:+.1f}%)")
print()

if v8_covs == 7 and delta_avg < -10:
    print("VERDICT: V8 IMPROVEMENT. Ready for online submission.")
elif v8_covs < 7:
    print("VERDICT: V8 FAILS DetCov — do NOT submit.")
elif delta_avg > 10:
    print("VERDICT: V8 WORSE — do NOT submit.")
else:
    print("VERDICT: V8 NEUTRAL. Marginal or no improvement.")
