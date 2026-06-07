# Strategy: scarce_route_ratio_guard
# Direction: scarce_branch_only
# Rationale: 仅修改稀缺分支中备份阶段的候选选择逻辑，将备份数量从固定3改为按courier/task比例动态调整，同时增加边际增益下限阈值，保持正常场景不变，不会退化成cost_first

"""solver.py — V9_TaskCountRoute (guarded scarce backup ratio).

Strategy: 仅修改稀缺分支备份阶段：
- 备份数量从固定3改为 min(max(1, int(5 * (1 - c/t))), 3) 按供需比动态调整
- 边际增益阈值从0.1提升到 max(0.1, 0.15 * (1 - c/t)) 防止低质量备份
- 正常/低意愿/分桶分支完全不变
"""


def solve(input_text: str) -> list:
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

    n_tasks = len(all_tasks)

    if courier_task_ratio < 0.8:
        return _solve_scarce(candidates, all_tasks, all_couriers_set, courier_task_ratio)
    elif mean_willingness < 0.25:
        return _solve_low_willingness(candidates)
    elif n_tasks <= 15 or n_tasks >= 40:
        return _solve_bucketed(candidates)
    else:
        return _solve_normal(candidates)


# --- bucketed: 意愿分桶+桶内成本排序 (V6 normal, 用于小/大任务) ---
def _solve_bucketed(candidates):
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


# --- normal: GreedyRatio (willingness/score 降序) ---
def _solve_normal(candidates):
    candidates.sort(key=lambda x: x[3] / max(x[2], 0.001), reverse=True)

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


# --- low_willingness: 意愿分桶+桶内性价比排序 (V6, 保持) ---
def _solve_low_willingness(candidates):
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


# --- scarce: 集合覆盖 + 动态备份 (guard: 按供需比动态调整备份数量和阈值) ---
def _solve_scarce(candidates, all_tasks, all_couriers_set, courier_task_ratio):
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

    # 阶段2：动态备份 — 按供需比动态调整备份数量和阈值
    unused = [cid for cid in all_couriers_set if cid not in assigned_couriers]
    
    # c/t 越低说明骑手越稀缺，备份数量应减少，阈值应升高
    scarcity_factor = 1.0 - courier_task_ratio  # 0.0~1.0, 越大越稀缺
    max_backups = min(max(1, int(5 * scarcity_factor)), 3)  # 稀缺时1~2个，充足时最多3个
    gain_threshold = max(0.1, 0.15 * scarcity_factor)  # 稀缺时阈值升高到0.15，正常时保持0.1
    
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

        if best_task_ids and best_marginal_gain > gain_threshold:
            result.append((",".join(best_task_ids), [courier_id]))
            for t in best_task_ids:
                task_cov_prob[t] = 1.0 - (1.0 - task_cov_prob.get(t, 0.0)) * (1.0 - best_backup_will)
            max_backups -= 1

    return result