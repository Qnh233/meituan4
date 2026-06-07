"""Quick local eval: test solver.py against calibrated presets. DetCov-first protocol."""
import sys, os, time, importlib.util

sys.path.insert(0, os.path.dirname(__file__))
from data_generator import generate, CALIBRATED_PRESETS

PRESET_KEYS = ["calibrated_tiny", "calibrated_small", "calibrated_medium",
               "calibrated_large", "calibrated_scarce", "calibrated_low_will",
               "calibrated_high_noise"]

# Online targets from V6
ONLINE = {"tiny": 210, "small": 452, "medium": 867, "large": 1076,
          "scarce": 1795, "low_will": 2298, "high_noise": 903}

# V9 online scores (for comparison)
V9_ONLINE = {"tiny": 210, "small": 452, "medium_201": 726, "medium_202": 850,
             "medium_203": 877, "large_301": 1076, "large_302": 1035,
             "scarce": 1795, "low_will": 2298, "high_noise": 803}


def eval_solver(solve_fn, n_runs=3):
    """Run solver on all calibrated presets. Returns per-preset DetScore and DetCov."""
    results = {}
    for preset_key in PRESET_KEYS:
        short = preset_key.replace("calibrated_", "")
        scores = []
        covs = []
        times = []
        for seed in range(n_runs):
            preset = CALIBRATED_PRESETS[preset_key]
            params = dict(preset["params"])
            params["seed"] = seed
            data = generate(**params)
            start = time.time()
            result = solve_fn(data)
            elapsed = (time.time() - start) * 1000
            times.append(elapsed)

            # Compute DetScore and DetCov
            all_tasks = set()
            for line in data.strip().splitlines()[1:]:
                parts = line.split("\t")
                if len(parts) >= 4:
                    for t in parts[0].split(","):
                        all_tasks.add(t.strip())

            covered = set()
            det_score = 0.0
            # Build score lookup
            score_lookup = {}
            for line in data.strip().splitlines()[1:]:
                parts = line.split("\t")
                if len(parts) >= 4:
                    score_lookup[(parts[0].strip(), parts[1].strip())] = float(parts[2])

            for ts_str, cs_list in result:
                cid = cs_list[0] if cs_list else ""
                task_ids = tuple(ts_str.split(","))
                covered.update(task_ids)
                key = (ts_str, cid)
                if key in score_lookup:
                    det_score += score_lookup[key]

            det_cov = len(covered) / max(len(all_tasks), 1)
            scores.append(det_score)
            covs.append(det_cov)

        avg_score = sum(scores) / len(scores)
        avg_cov = sum(covs) / len(covs)
        avg_time = sum(times) / len(times)
        results[short] = {"det_score": avg_score, "det_cov": avg_cov, "time_ms": avg_time}
    return results


def compare(baseline_results, new_results):
    """Print comparison table."""
    print(f"{'Preset':<15} {'V9_Score':>10} {'New_Score':>10} {'Delta':>10} {'V9_Cov':>8} {'New_Cov':>8} {'Time_ms':>8}")
    print("-" * 75)
    total_delta = 0
    for key in PRESET_KEYS:
        short = key.replace("calibrated_", "")
        b = baseline_results.get(short, {})
        n = new_results.get(short, {})
        b_score = b.get("det_score", 0)
        n_score = n.get("det_score", 0)
        b_cov = b.get("det_cov", 0)
        n_cov = n.get("det_cov", 0)
        delta = n_score - b_score
        total_delta += delta
        print(f"{short:<15} {b_score:>10.1f} {n_score:>10.1f} {delta:>+10.1f} {b_cov:>8.3f} {n_cov:>8.3f} {n.get('time_ms',0):>8.0f}")
    print("-" * 75)
    avg_delta = total_delta / len(PRESET_KEYS)
    print(f"{'AVERAGE':<15} {'':>10} {'':>10} {avg_delta:>+10.1f}")
    return avg_delta


if __name__ == "__main__":
    # Load current solver
    solver_path = os.path.join(os.path.dirname(__file__), "solver.py")
    spec = importlib.util.spec_from_file_location("solver", solver_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    new_solve = mod.solve

    # Load V9 baseline
    v9_path = os.path.join(os.path.dirname(__file__), "snapshots",
                           "solver_v9_taskcount_20260515_233830.py")
    spec_v9 = importlib.util.spec_from_file_location("v9", v9_path)
    mod_v9 = importlib.util.module_from_spec(spec_v9)
    spec_v9.loader.exec_module(mod_v9)
    v9_solve = mod_v9.solve

    print("=" * 75)
    print("V9 BASELINE")
    print("=" * 75)
    v9_results = eval_solver(v9_solve)

    print("\n" + "=" * 75)
    print("CURRENT SOLVER vs V9 BASELINE")
    print("=" * 75)
    new_results = eval_solver(new_solve)
    avg_delta = compare(v9_results, new_results)

    if avg_delta < -1:
        print(f"\n>>> IMPROVEMENT: avg -{-avg_delta:.1f} points. Worth submitting.")
    elif avg_delta > 1:
        print(f"\n>>> REGRESSION: avg +{avg_delta:.1f} points. DON'T submit.")
    else:
        print(f"\n>>> NEUTRAL: avg {avg_delta:+.1f} points. Borderline.")
