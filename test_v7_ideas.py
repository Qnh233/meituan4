"""Test V7 ideas for improving upon V6."""
import sys, os, json, random, math

sys.path.insert(0, os.path.dirname(__file__))
from parser import parse
from judge import evaluate_deterministic, evaluate_monte_carlo

# ═══════════════════════════════════════════════════════
# V6 baseline (exact copy of solver_adaptive_v6)
# ═══════════════════════════════════════════════════════

def v6_solve(input_text: str) -> list:
    lines = input_text.strip().splitlines()
    if not lines:
        return []
    start = 1 if lines[0].startswith("task_id_list") else 0
    candidates = []
    all_tasks = set()
    all_couriers_set = set()
    will_sum = 0.0
    for line in lines[start:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        task_id_list_str, courier_id, score_str, willingness_str = parts[:4]
        try:
            willingness = float(willingness_str)
        except ValueError:
            continue
        if willingness <= 0:
            continue
        task_ids = tuple(t.strip() for t in task_id_list_str.split(",") if t.strip())
        if not task_ids:
            continue
        try:
            score = float(score_str)
        except ValueError:
            score = float("inf")
        candidates.append((task_ids, courier_id.strip(), score, willingness))
        all_couriers_set.add(courier_id.strip())
        all_tasks.update(task_ids)
        will_sum += willingness
    if not all_tasks:
        return []
    courier_task_ratio = len(all_couriers_set) / max(len(all_tasks), 1)
    mean_willingness = will_sum / max(len(candidates), 1)
    if courier_task_ratio < 0.8:
        return _v6_scarce(candidates, all_tasks, all_couriers_set)
    elif mean_willingness < 0.25:
        return _v6_low_will(candidates)
    else:
        return _v6_normal(candidates)

def _v6_normal(candidates):
    candidates.sort(key=lambda x: (-int(x[3] * 10), x[2]))
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

def _v6_low_will(candidates):
    candidates.sort(key=lambda x: (-int(x[3] * 10), -x[3] / max(x[2], 0.001)))
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

def _v6_scarce(candidates, all_tasks, all_couriers_set):
    total_tasks = len(all_tasks)
    courier_cands = {}
    for c in candidates:
        courier_cands.setdefault(c[1], []).append(c)
    assigned_couriers = set()
    assigned_tasks = set()
    result = []
    task_primary_will = {}
    for _ in range(len(all_couriers_set)):
        if len(assigned_tasks) >= total_tasks:
            break
        best_idx = -1
        best_score = -1.0
        best_score_secondary = float("inf")
        for idx, (task_ids, courier_id, score, willingness) in enumerate(candidates):
            if courier_id in assigned_couriers:
                continue
            if any(t in assigned_tasks for t in task_ids):
                continue
            expected = len(task_ids) * willingness
            if expected > best_score or (expected == best_score and score < best_score_secondary):
                best_score = expected
                best_score_secondary = score
                best_idx = idx
        if best_idx < 0:
            break
        task_ids, courier_id, score, willingness = candidates[best_idx]
        assigned_couriers.add(courier_id)
        assigned_tasks.update(task_ids)
        result.append((",".join(task_ids), [courier_id]))
        for t in task_ids:
            task_primary_will[t] = willingness
    unused = [cid for cid in all_couriers_set if cid not in assigned_couriers]
    max_backups = min(3, len(unused))
    task_cov_prob = dict(task_primary_will)
    for courier_id in unused:
        if max_backups <= 0:
            break
        best_task_ids = None
        best_marginal_gain = -1.0
        best_backup_will = 0.0
        for task_ids, cid, score, willingness in courier_cands.get(courier_id, []):
            gain = 0.0
            for t in task_ids:
                gain += willingness * (1.0 - task_cov_prob.get(t, 0.0))
            if gain > best_marginal_gain or (gain == best_marginal_gain and willingness > best_backup_will):
                best_marginal_gain = gain
                best_backup_will = willingness
                best_task_ids = task_ids
        if best_task_ids and best_marginal_gain > 0.1:
            result.append((",".join(best_task_ids), [courier_id]))
            for t in best_task_ids:
                task_cov_prob[t] = 1.0 - (1.0 - task_cov_prob.get(t, 0.0)) * (1.0 - best_backup_will)
            max_backups -= 1
    return result


# ═══════════════════════════════════════════════════════
# V7 variants
# ═══════════════════════════════════════════════════════

# V7a: low_will with iterative coverage-driven backup (up to 8 backups)
def _v7a_low_will(candidates):
    """V6 low_will + iterative backup up to 8 with score-aware marginal gain."""
    candidates.sort(key=lambda x: (-int(x[3] * 10), -x[3] / max(x[2], 0.001)))

    assigned_couriers = set()
    assigned_tasks = set()
    result = []
    task_primary_will = {}

    # Phase 1: primary assignment (same as V6)
    for task_ids, courier_id, score, willingness in candidates:
        if courier_id in assigned_couriers:
            continue
        if any(t in assigned_tasks for t in task_ids):
            continue
        assigned_couriers.add(courier_id)
        assigned_tasks.update(task_ids)
        result.append((",".join(task_ids), [courier_id]))
        for t in task_ids:
            if t not in task_primary_will or willingness > task_primary_will[t]:
                task_primary_will[t] = willingness

    # Phase 2: coverage-driven backup
    # Build courier -> candidates index for unused
    courier_cands = {}
    for c in candidates:
        courier_cands.setdefault(c[1], []).append(c)

    all_tasks_sorted = sorted(task_primary_will.keys(), key=lambda t: task_primary_will[t])
    cov_prob = dict(task_primary_will)

    max_backups = 8
    UNCOVERED_COST = 100.0  # penalty per uncovered task

    for _ in range(max_backups):
        best_courier = None
        best_task_ids = None
        best_net_benefit = -float("inf")

        for cid in set(c[1] for c in candidates) - assigned_couriers:
            for task_ids, _, score, willingness in courier_cands.get(cid, []):
                # Compute marginal coverage gain
                gain = 0.0
                for t in task_ids:
                    gain += willingness * (1.0 - cov_prob.get(t, 0.0))
                # Benefit = coverage gain * uncovered_penalty - score cost
                net_benefit = gain * UNCOVERED_COST - score
                if net_benefit > best_net_benefit:
                    best_net_benefit = net_benefit
                    best_courier = (task_ids, cid, score, willingness)

        if best_courier and best_net_benefit > 0:
            task_ids, cid, score, willingness = best_courier
            result.append((",".join(task_ids), [cid]))
            assigned_couriers.add(cid)
            for t in task_ids:
                cov_prob[t] = 1.0 - (1.0 - cov_prob.get(t, 0.0)) * (1.0 - willingness)
        else:
            break

    return result


# V7b: low_will with cost-bounded backup (simpler: just add up to 5 backups targeting lowest-will tasks)
def _v7b_low_will(candidates):
    """V6 low_will + 5 simple backups targeting lowest primary-willingness tasks."""
    candidates.sort(key=lambda x: (-int(x[3] * 10), -x[3] / max(x[2], 0.001)))

    assigned_couriers = set()
    assigned_tasks = set()
    result = []
    task_primary_will = {}

    for task_ids, courier_id, score, willingness in candidates:
        if courier_id in assigned_couriers:
            continue
        if any(t in assigned_tasks for t in task_ids):
            continue
        assigned_couriers.add(courier_id)
        assigned_tasks.update(task_ids)
        result.append((",".join(task_ids), [courier_id]))
        for t in task_ids:
            if t not in task_primary_will or willingness > task_primary_will[t]:
                task_primary_will[t] = willingness

    # Find 5 riskiest tasks
    risky = set(sorted(task_primary_will.keys(), key=lambda t: task_primary_will[t])[:5])

    # Find best unused couriers for risky tasks
    backup_pool = []
    for task_ids, courier_id, score, willingness in candidates:
        if courier_id in assigned_couriers:
            continue
        risky_hits = sum(1 for t in task_ids if t in risky)
        if risky_hits > 0:
            # Ratio considering both risky coverage and cost
            backup_pool.append((risky_hits * willingness / max(score, 0.001), task_ids, courier_id, score, willingness))

    backup_pool.sort(key=lambda x: -x[0])

    max_backups = 5
    for _, task_ids, cid, score, willingness in backup_pool:
        if max_backups <= 0:
            break
        if cid in assigned_couriers:
            continue
        result.append((",".join(task_ids), [cid]))
        assigned_couriers.add(cid)
        max_backups -= 1

    return result


# V7c: normal mode with tiny tweak — softer bucket boundaries
def _v7c_normal(candidates):
    """Bucket by willingness, but within bucket sort by score - 10*willingness (tiny cost bonus for high will)."""
    # Same bucketing, but within bucket: prefer slightly higher willingness at same cost
    candidates.sort(key=lambda x: (-int(x[3] * 10), x[2] - x[3] * 5))

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


def v7a_solve(input_text):
    """V7a: low_will backup 8, normal unchanged, scarce unchanged."""
    lines = input_text.strip().splitlines()
    if not lines:
        return []
    start = 1 if lines[0].startswith("task_id_list") else 0
    candidates = []
    all_tasks = set()
    all_couriers_set = set()
    will_sum = 0.0
    for line in lines[start:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        task_id_list_str, courier_id, score_str, willingness_str = parts[:4]
        try:
            willingness = float(willingness_str)
        except ValueError:
            continue
        if willingness <= 0:
            continue
        task_ids = tuple(t.strip() for t in task_id_list_str.split(",") if t.strip())
        if not task_ids:
            continue
        try:
            score = float(score_str)
        except ValueError:
            score = float("inf")
        candidates.append((task_ids, courier_id.strip(), score, willingness))
        all_couriers_set.add(courier_id.strip())
        all_tasks.update(task_ids)
        will_sum += willingness
    if not all_tasks:
        return []
    courier_task_ratio = len(all_couriers_set) / max(len(all_tasks), 1)
    mean_willingness = will_sum / max(len(candidates), 1)
    if courier_task_ratio < 0.8:
        return _v6_scarce(candidates, all_tasks, all_couriers_set)
    elif mean_willingness < 0.25:
        return _v7a_low_will(candidates)
    else:
        return _v6_normal(candidates)


def v7b_solve(input_text):
    """V7b: low_will backup 5 simple, normal unchanged, scarce unchanged."""
    lines = input_text.strip().splitlines()
    if not lines:
        return []
    start = 1 if lines[0].startswith("task_id_list") else 0
    candidates = []
    all_tasks = set()
    all_couriers_set = set()
    will_sum = 0.0
    for line in lines[start:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        task_id_list_str, courier_id, score_str, willingness_str = parts[:4]
        try:
            willingness = float(willingness_str)
        except ValueError:
            continue
        if willingness <= 0:
            continue
        task_ids = tuple(t.strip() for t in task_id_list_str.split(",") if t.strip())
        if not task_ids:
            continue
        try:
            score = float(score_str)
        except ValueError:
            score = float("inf")
        candidates.append((task_ids, courier_id.strip(), score, willingness))
        all_couriers_set.add(courier_id.strip())
        all_tasks.update(task_ids)
        will_sum += willingness
    if not all_tasks:
        return []
    courier_task_ratio = len(all_couriers_set) / max(len(all_tasks), 1)
    mean_willingness = will_sum / max(len(candidates), 1)
    if courier_task_ratio < 0.8:
        return _v6_scarce(candidates, all_tasks, all_couriers_set)
    elif mean_willingness < 0.25:
        return _v7b_low_will(candidates)
    else:
        return _v6_normal(candidates)


def v7c_solve(input_text):
    """V7c: normal with softer bucket sort, low_will unchanged, scarce unchanged."""
    lines = input_text.strip().splitlines()
    if not lines:
        return []
    start = 1 if lines[0].startswith("task_id_list") else 0
    candidates = []
    all_tasks = set()
    all_couriers_set = set()
    will_sum = 0.0
    for line in lines[start:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        task_id_list_str, courier_id, score_str, willingness_str = parts[:4]
        try:
            willingness = float(willingness_str)
        except ValueError:
            continue
        if willingness <= 0:
            continue
        task_ids = tuple(t.strip() for t in task_id_list_str.split(",") if t.strip())
        if not task_ids:
            continue
        try:
            score = float(score_str)
        except ValueError:
            score = float("inf")
        candidates.append((task_ids, courier_id.strip(), score, willingness))
        all_couriers_set.add(courier_id.strip())
        all_tasks.update(task_ids)
        will_sum += willingness
    if not all_tasks:
        return []
    courier_task_ratio = len(all_couriers_set) / max(len(all_tasks), 1)
    mean_willingness = will_sum / max(len(candidates), 1)
    if courier_task_ratio < 0.8:
        return _v6_scarce(candidates, all_tasks, all_couriers_set)
    elif mean_willingness < 0.25:
        return _v6_low_will(candidates)
    else:
        return _v7c_normal(candidates)


# ═══════════════════════════════════════════════════════
# Benchmark
# ═══════════════════════════════════════════════════════

def generate_data():
    from data_generator import generate, PRESETS
    preset_names = [
        "large", "medium", "high_noise", "small", "tiny",
        "low_willingness", "scarce_couriers", "scarce_v2", "scarce_v3",
    ]
    datasets = {}
    for name in preset_names:
        preset = PRESETS[name]
        seed = hash(name) % 10000
        params = preset["params"].copy()
        params["seed"] = seed
        text = generate(**params)
        datasets[name] = text
    return datasets


def eval_one(name, plan, data, n=300):
    det = evaluate_deterministic(plan, data)
    mc = evaluate_monte_carlo(plan, data, n_simulations=n, seed=42)
    return {
        "name": name,
        "det_cov": det.coverage_rate,
        "det_score": det.total_score,
        "mc_cov": mc.coverage_rate,
        "mc_score": mc.total_score,
        "est_pen": mc.estimated_penalty,
        "entries": len(plan),
        "uncovered": mc.uncovered_tasks,
    }


def benchmark():
    datasets = generate_data()
    strategies = {
        "V6": v6_solve,
        "V7a": v7a_solve,   # low_will: backup up to 8, net-benefit gated
        "V7b": v7b_solve,   # low_will: backup 5 simple
        "V7c": v7c_solve,   # normal: softer bucket sort
    }

    results = {}
    for strat_name, strat_fn in strategies.items():
        results[strat_name] = {}
        for ds_name, text in datasets.items():
            plan = strat_fn(text)
            data = parse(text)
            results[strat_name][ds_name] = eval_one(ds_name, plan, data)

    # Print table
    header = f"{'Dataset':<22} | {'Strat':<5} | {'DetCov':>6} {'DetSc':>8} | {'MCCov':>6} {'MCSc':>8} | {'EstPen':>9} | {'Ent':>4} | {'Unc':>4}"
    sep = "-" * len(header)
    print(sep)
    print(header)
    print(sep)

    for ds_name in datasets:
        for strat_name in strategies:
            r = results[strat_name][ds_name]
            v6 = results["V6"][ds_name]
            delta = r["est_pen"] - v6["est_pen"]
            flag = " <<<" if delta < -5 else (" >>>" if delta > 5 else "")
            print(f"{ds_name:<22} | {strat_name:<5} | {r['det_cov']:>6.3f} {r['det_score']:>8.1f} | "
                  f"{r['mc_cov']:>6.3f} {r['mc_score']:>8.1f} | {r['est_pen']:>9.1f} | "
                  f"{r['entries']:>4} | {r['uncovered']:>4}{flag}")
        print()

    # Summary
    print(sep)
    print("SUMMARY: Avg EstPen across all 9 datasets")
    print(sep)
    for strat_name in strategies:
        avg = sum(results[strat_name][ds]["est_pen"] for ds in datasets) / len(datasets)
        v6avg = sum(results["V6"][ds]["est_pen"] for ds in datasets) / len(datasets)
        print(f"  {strat_name}: {avg:.1f}  (delta vs V6: {avg - v6avg:+.1f})")

    # Detailed deltas per strategy
    print()
    print("Per-strategy per-dataset delta vs V6:")
    for strat_name in ["V7a", "V7b", "V7c"]:
        print(f"  {strat_name}:")
        for ds_name in datasets:
            d = results[strat_name][ds_name]["est_pen"] - results["V6"][ds_name]["est_pen"]
            dc = results[strat_name][ds_name]["mc_cov"] - results["V6"][ds_name]["mc_cov"]
            print(f"    {ds_name:<22} EstPen {d:+7.1f}  MCCov {dc:+.3f}")


if __name__ == "__main__":
    benchmark()
