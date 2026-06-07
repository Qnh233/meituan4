# Strategy: effective_cost_cover_v1
# Direction: expected_penalty_key
# Rationale: Online detail suggests cost ~= score + missed-acceptance penalty, so rank by score per task plus risk.

"""Keeta solver: dependency-free expected-cost greedy cover.

The solver keeps one primary assignment per task and one use per courier.
It ranks each candidate by:

    total_score / task_count + penalty * (1 - willingness)

This keeps the coverage discipline from the old V9 route but optimizes a key
closer to the online penalty than raw score, bucketed score, or w/score alone.
"""


def solve(input_text: str) -> list:
    lines = input_text.strip().splitlines()
    if not lines:
        return []

    start = 1 if lines[0].startswith("task_id_list") else 0
    candidates = []
    all_tasks = set()
    all_couriers = set()
    will_sum = 0.0

    for line in lines[start:]:
        parts = line.strip().split("\t")
        if len(parts) < 4:
            continue
        task_id_list_str, courier_id, score_str, willingness_str = parts[:4]
        try:
            willingness = float(willingness_str)
            score = float(score_str)
        except ValueError:
            continue
        if willingness <= 0:
            continue

        task_ids = tuple(t.strip() for t in task_id_list_str.split(",") if t.strip())
        if not task_ids:
            continue

        cid = courier_id.strip()
        candidates.append((task_ids, cid, score, willingness))
        all_tasks.update(task_ids)
        all_couriers.add(cid)
        will_sum += willingness

    if not all_tasks:
        return []

    n_tasks = len(all_tasks)
    courier_task_ratio = len(all_couriers) / max(n_tasks, 1)
    mean_willingness = will_sum / max(len(candidates), 1)

    # Tuned conservatively from online result details and synthetic calibrated
    # cases. Scarce/low-will data tend to overpay for risk if P is too high.
    if courier_task_ratio < 0.8:
        old = _solve_scarce_v9(candidates, all_tasks, all_couriers, courier_task_ratio)
        new = _solve_scarce_cost_cover(candidates, all_tasks, 190.0)
        old = _improve_scarce_pair_swaps(old, candidates, 190.0)
        new = _improve_scarce_pair_swaps(new, candidates, 190.0)
        if new and _scarce_plan_cost(new, candidates, 190.0) < _scarce_plan_cost(old, candidates, 190.0):
            return new
        return old
    elif mean_willingness < 0.25:
        penalty = 70.0
    elif n_tasks <= 15:
        penalty = 85.0
    elif n_tasks >= 40:
        penalty = 80.0
    else:
        penalty = 90.0

    greedy = _solve_effective_cover(candidates, all_tasks, penalty)
    matching = _solve_hungarian_singles(candidates, all_tasks, all_couriers, penalty)
    if matching and _plan_expected_cost(matching, candidates, penalty) < _plan_expected_cost(greedy, candidates, penalty):
        primary = matching
    else:
        primary = greedy
    backed = _add_single_backups(primary, candidates, penalty, 1, True)
    if len(all_couriers) >= 2 * len(all_tasks):
        paired = _solve_low_will_pairs(candidates, all_tasks, 90.0)
        if paired and _multi_single_plan_cost(paired, candidates, 90.0) < _multi_single_plan_cost(backed, candidates, 90.0):
            return paired
    return backed


def _solve_effective_cover(candidates, all_tasks, penalty):
    candidates.sort(key=lambda x: (
        x[2] / max(len(x[0]), 1) + penalty * (1.0 - x[3]),
        x[2],
        -x[3],
    ))

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
        if len(assigned_tasks) >= len(all_tasks):
            break

    return result


def _solve_hungarian_singles(candidates, all_tasks, all_couriers, penalty):
    task_list = sorted(all_tasks)
    courier_list = sorted(all_couriers)
    n = len(task_list)
    m = len(courier_list)
    if n == 0 or m < n:
        return []

    task_idx = {t: i for i, t in enumerate(task_list)}
    courier_idx = {c: i for i, c in enumerate(courier_list)}
    big = 1000000000.0
    cost = [[big] * m for _ in range(n)]
    choice = [[None] * m for _ in range(n)]

    for task_ids, courier_id, score, willingness in candidates:
        if len(task_ids) != 1:
            continue
        i = task_idx.get(task_ids[0])
        j = courier_idx.get(courier_id)
        if i is None or j is None:
            continue
        value = score + penalty * (1.0 - willingness)
        if value < cost[i][j]:
            cost[i][j] = value
            choice[i][j] = (task_ids[0], courier_id)

    # Rectangular Hungarian algorithm, minimizing n task rows over m courier columns.
    u = [0.0] * (n + 1)
    v = [0.0] * (m + 1)
    p = [0] * (m + 1)
    way = [0] * (m + 1)

    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [float("inf")] * (m + 1)
        used = [False] * (m + 1)
        while True:
            used[j0] = True
            i0 = p[j0]
            delta = float("inf")
            j1 = 0
            row = cost[i0 - 1]
            for j in range(1, m + 1):
                if not used[j]:
                    cur = row[j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j] = cur
                        way[j] = j0
                    if minv[j] < delta:
                        delta = minv[j]
                        j1 = j
            if delta >= big:
                return []
            for j in range(m + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break

    assign = [0] * (n + 1)
    for j in range(1, m + 1):
        if p[j] > 0:
            assign[p[j]] = j

    result = []
    for i in range(1, n + 1):
        j = assign[i]
        if j <= 0:
            return []
        picked = choice[i - 1][j - 1]
        if picked is None:
            return []
        result.append((picked[0], [picked[1]]))
    return result


def _plan_expected_cost(plan, candidates, penalty):
    lookup = {}
    for task_ids, courier_id, score, willingness in candidates:
        key = (",".join(task_ids), courier_id)
        value = score + penalty * len(task_ids) * (1.0 - willingness)
        old = lookup.get(key)
        if old is None or value < old:
            lookup[key] = value

    total = 0.0
    covered = set()
    used = set()
    for task_str, courier_ids in plan:
        if not courier_ids:
            continue
        courier_id = courier_ids[0]
        if courier_id in used:
            return float("inf")
        used.add(courier_id)
        value = lookup.get((task_str, courier_id))
        if value is None:
            return float("inf")
        total += value
        for t in task_str.split(","):
            if t:
                covered.add(t)
    return total - 0.0001 * len(covered)


def _add_single_backups(plan, candidates, penalty, max_extra_per_task, force_one=False):
    task_to_entry = {}
    used = set()
    for idx, (task_str, courier_ids) in enumerate(plan):
        for cid in courier_ids:
            used.add(cid)
        if "," not in task_str:
            task_to_entry[task_str] = idx

    task_prob = {}
    for task_str, courier_ids in plan:
        if "," in task_str or not courier_ids:
            continue
        p = 0.0
        for task_ids, cid, score, willingness in candidates:
            if task_ids == (task_str,) and cid in courier_ids:
                p = 1.0 - (1.0 - p) * (1.0 - willingness)
        task_prob[task_str] = p

    backup_options = []
    for task_ids, courier_id, score, willingness in candidates:
        if len(task_ids) != 1:
            continue
        task = task_ids[0]
        if task not in task_to_entry or courier_id in used:
            continue
        current_p = task_prob.get(task, 0.0)
        # Marginal objective assumes online cost ~= score + P * miss_prob.
        gain = penalty * current_p * willingness - score
        if force_one or gain > 0.0:
            backup_options.append((gain, task, courier_id, willingness, score))

    backup_options.sort(key=lambda x: (-x[0], x[4]))
    extra_count = {}
    result = [(task_str, list(courier_ids)) for task_str, courier_ids in plan]
    for gain, task, courier_id, willingness, score in backup_options:
        if courier_id in used:
            continue
        count = extra_count.get(task, 0)
        if count >= max_extra_per_task:
            continue
        idx = task_to_entry[task]
        result[idx][1].append(courier_id)
        used.add(courier_id)
        extra_count[task] = count + 1
    single_score = {}
    for task_ids, courier_id, score, willingness in candidates:
        if len(task_ids) == 1:
            single_score[(task_ids[0], courier_id)] = score
    for task_str, courier_ids in result:
        if "," not in task_str and len(courier_ids) > 1:
            courier_ids.sort(key=lambda cid: single_score.get((task_str, cid), float("inf")))
    return result


def _solve_low_will_pairs(candidates, all_tasks, penalty):
    by_task = {t: {} for t in all_tasks}
    for task_ids, courier_id, score, willingness in candidates:
        if len(task_ids) != 1:
            continue
        task = task_ids[0]
        old = by_task.get(task, {}).get(courier_id)
        if old is None or score + penalty * (1.0 - willingness) < old[0] + penalty * (1.0 - old[1]):
            by_task[task][courier_id] = (score, willingness)

    pair_options = {}
    for task, cmap in by_task.items():
        singles = [(cid, sw[0], sw[1]) for cid, sw in cmap.items()]
        if len(singles) < 2:
            return []
        singles.sort(key=lambda x: (x[1] + penalty * (1.0 - x[2]), x[1], -x[2]))
        top = singles[:16]
        opts = []
        for i in range(len(top)):
            for j in range(i + 1, len(top)):
                c1, s1, w1 = top[i]
                c2, s2, w2 = top[j]
                if s2 < s1:
                    c1, s1, w1, c2, s2, w2 = c2, s2, w2, c1, s1, w1
                p = 1.0 - (1.0 - w1) * (1.0 - w2)
                if p <= 0.0:
                    continue
                expected = (w1 * s1 + (1.0 - w1) * w2 * s2) / p
                cost = expected + penalty * (1.0 - p)
                opts.append((cost, task, c1, c2))
        if not opts:
            return []
        opts.sort(key=lambda x: x[0])
        pair_options[task] = opts[:80]

    used = set()
    remaining = set(all_tasks)
    result = []
    while remaining:
        best_pick = None
        best_regret = -float("inf")
        for task in list(remaining):
            feasible = [o for o in pair_options[task] if o[2] not in used and o[3] not in used]
            if not feasible:
                return []
            first = feasible[0]
            second_cost = feasible[1][0] if len(feasible) > 1 else first[0] + 1000.0
            regret = second_cost - first[0]
            if regret > best_regret:
                best_regret = regret
                best_pick = first
        _, task, c1, c2 = best_pick
        result.append((task, [c1, c2]))
        used.add(c1)
        used.add(c2)
        remaining.remove(task)
    return result


def _multi_single_plan_cost(plan, candidates, penalty):
    lookup = {}
    for task_ids, courier_id, score, willingness in candidates:
        if len(task_ids) == 1:
            lookup[(task_ids[0], courier_id)] = (score, willingness)
    total = 0.0
    used = set()
    for task, courier_ids in plan:
        if "," in task or not courier_ids:
            return float("inf")
        ordered = []
        for cid in courier_ids:
            if cid in used:
                return float("inf")
            used.add(cid)
            sw = lookup.get((task, cid))
            if sw is None:
                return float("inf")
            ordered.append((sw[0], sw[1]))
        ordered.sort(key=lambda x: x[0])
        fail = 1.0
        weighted_score = 0.0
        for score, willingness in ordered:
            weighted_score += fail * willingness * score
            fail *= (1.0 - willingness)
        p = 1.0 - fail
        if p <= 0.0:
            return float("inf")
        total += weighted_score / p + penalty * fail
    return total


def _solve_scarce_cost_cover(candidates, all_tasks, route_penalty):
    total_tasks = len(all_tasks)
    preferred = [c for c in candidates if len(c[0]) >= 2]
    preferred.sort(key=lambda x: (
        (x[2] + route_penalty * (1.0 - x[3])) / len(x[0]),
        -len(x[0]),
        x[2],
        -x[3],
    ))

    assigned_couriers = set()
    assigned_tasks = set()
    result = []
    for task_ids, courier_id, score, willingness in preferred:
        if courier_id in assigned_couriers:
            continue
        if any(t in assigned_tasks for t in task_ids):
            continue
        assigned_couriers.add(courier_id)
        assigned_tasks.update(task_ids)
        result.append((",".join(task_ids), [courier_id]))
        if len(assigned_tasks) >= total_tasks:
            break

    if len(assigned_tasks) < total_tasks:
        fallback = sorted(candidates, key=lambda x: (
            (x[2] + route_penalty * (1.0 - x[3])) / len(x[0]),
            x[2],
            -x[3],
        ))
        for task_ids, courier_id, score, willingness in fallback:
            if courier_id in assigned_couriers:
                continue
            if any(t in assigned_tasks for t in task_ids):
                continue
            assigned_couriers.add(courier_id)
            assigned_tasks.update(task_ids)
            result.append((",".join(task_ids), [courier_id]))
            if len(assigned_tasks) >= total_tasks:
                break

    if len(assigned_tasks) < total_tasks:
        return []
    return result


def _scarce_plan_cost(plan, candidates, route_penalty):
    lookup = {}
    for task_ids, courier_id, score, willingness in candidates:
        key = (",".join(task_ids), courier_id)
        value = score + route_penalty * (1.0 - willingness)
        old = lookup.get(key)
        if old is None or value < old:
            lookup[key] = value

    total = 0.0
    used = set()
    covered = set()
    for task_str, courier_ids in plan:
        if not courier_ids:
            continue
        cid = courier_ids[0]
        if cid in used:
            return float("inf")
        used.add(cid)
        value = lookup.get((task_str, cid))
        if value is None:
            return float("inf")
        total += value
        for t in task_str.split(","):
            if t:
                covered.add(t)
    return total - 0.001 * len(covered)


def _improve_scarce_pair_swaps(plan, candidates, route_penalty):
    if not plan:
        return plan

    pair_lookup = {}
    for task_ids, courier_id, score, willingness in candidates:
        if len(task_ids) != 2:
            continue
        key = (frozenset(task_ids), courier_id)
        value = score + route_penalty * (1.0 - willingness)
        old = pair_lookup.get(key)
        if old is None or value < old[0]:
            pair_lookup[key] = (value, ",".join(task_ids), courier_id)

    result = [(task_str, list(courier_ids)) for task_str, courier_ids in plan]
    for _ in range(20):
        improved = False
        n = len(result)
        for i in range(n):
            task_i, couriers_i = result[i]
            if len(task_i.split(",")) != 2 or not couriers_i:
                continue
            ci = couriers_i[0]
            ti = [t for t in task_i.split(",") if t]
            for j in range(i + 1, n):
                task_j, couriers_j = result[j]
                if len(task_j.split(",")) != 2 or not couriers_j:
                    continue
                cj = couriers_j[0]
                tj = [t for t in task_j.split(",") if t]
                four = ti + tj
                if len(set(four)) != 4:
                    continue

                left_current = pair_lookup.get((frozenset(ti), ci))
                right_current = pair_lookup.get((frozenset(tj), cj))
                if left_current is None or right_current is None:
                    continue
                current = left_current[0] + right_current[0]
                best = None
                partitions = [
                    ((four[0], four[1]), (four[2], four[3])),
                    ((four[0], four[2]), (four[1], four[3])),
                    ((four[0], four[3]), (four[1], four[2])),
                ]
                for a, b in partitions:
                    for ca, cb in ((ci, cj), (cj, ci)):
                        left = pair_lookup.get((frozenset(a), ca))
                        right = pair_lookup.get((frozenset(b), cb))
                        if left is None or right is None:
                            continue
                        value = left[0] + right[0]
                        if best is None or value < best[0]:
                            best = (value, (left[1], [left[2]]), (right[1], [right[2]]))
                if best is not None and best[0] + 0.0001 < current:
                    result[i] = best[1]
                    result[j] = best[2]
                    improved = True
                    break
            if improved:
                break
        if not improved:
            break
    return result


def _solve_scarce_v9(candidates, all_tasks, all_couriers_set, courier_task_ratio):
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
    scarcity_factor = 1.0 - courier_task_ratio
    max_backups = min(max(1, int(5 * scarcity_factor)), 3)
    gain_threshold = max(0.1, 0.15 * scarcity_factor)
    task_cov_prob = dict(task_primary_will)

    backup_candidates = []
    for courier_id in unused:
        best_gain = -1.0
        best_cost = float("inf")
        best_task_ids = None
        best_will = 0.0

        for task_ids, cid, score, willingness in courier_cands.get(courier_id, []):
            gain = 0.0
            for t in task_ids:
                gain += willingness * (1.0 - task_cov_prob.get(t, 0.0))
            if gain > best_gain or (gain == best_gain and score < best_cost):
                best_gain = gain
                best_cost = score
                best_task_ids = task_ids
                best_will = willingness

        if best_task_ids and best_gain > gain_threshold:
            ratio = best_gain / max(best_cost, 0.001)
            backup_candidates.append((ratio, best_gain, best_task_ids, courier_id, best_will, best_cost))

    backup_candidates.sort(key=lambda x: -x[0])

    selected_backup_couriers = set()
    for ratio, gain, task_ids, courier_id, willingness, score in backup_candidates:
        if len(selected_backup_couriers) >= max_backups:
            break
        if courier_id in selected_backup_couriers:
            continue

        result.append((",".join(task_ids), [courier_id]))
        selected_backup_couriers.add(courier_id)
        for t in task_ids:
            task_cov_prob[t] = 1.0 - (1.0 - task_cov_prob.get(t, 0.0)) * (1.0 - willingness)

    return result
