"""贪心 baseline 系列：按不同排序策略贪心分配。"""

from parser import ProblemData


def greedy_solve(data: ProblemData, *, sort_key: str = "score") -> list[tuple[str, list[str]]]:
    candidates = list(data.candidates)

    if sort_key == "score":
        candidates.sort(key=lambda c: c.total_score)
    elif sort_key == "willingness":
        candidates.sort(key=lambda c: c.willingness, reverse=True)
    elif sort_key == "ratio":
        candidates.sort(key=lambda c: c.willingness / max(c.total_score, 0.001), reverse=True)
    elif sort_key == "single_first":
        candidates.sort(key=lambda c: (c.task_count, c.total_score))
    else:
        candidates.sort(key=lambda c: c.total_score)

    assigned_couriers: set[str] = set()
    assigned_tasks: set[str] = set()
    result = []

    for c in candidates:
        if c.courier_id in assigned_couriers:
            continue
        if any(t in assigned_tasks for t in c.task_ids):
            continue
        if c.willingness <= 0:
            continue

        assigned_couriers.add(c.courier_id)
        assigned_tasks.update(c.task_ids)
        result.append((",".join(c.task_ids), [c.courier_id]))

    return result
