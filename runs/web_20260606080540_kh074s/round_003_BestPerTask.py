# Strategy: BestPerTask
# Description: 逐任务贪心：对每个未覆盖任务选最优候选，按 score 升序

def solve(input_text: str) -> list:
    lines = input_text.strip().splitlines()
    if not lines:
        return []
    start = 1 if lines[0].startswith("task_id_list") else 0
    task_cands = {}
    for line in lines[start:]:
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
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
        for t in task_ids:
            if t not in task_cands:
                task_cands[t] = []
            task_cands[t].append((task_ids, parts[1].strip(), score, willingness))
    # 每个 task 的候选按 score 排序
    for t in task_cands:
        task_cands[t].sort(key=lambda x: x[2])
    assigned_couriers = set()
    assigned_tasks = set()
    result = []
    # 按候选质量迭代：每次选全局最佳
    all_tasks = sorted(task_cands.keys())
    while True:
        best = None
        best_score = float("inf")
        for t in all_tasks:
            if t in assigned_tasks:
                continue
            for c in task_cands.get(t, []):
                if c[1] in assigned_couriers:
                    continue
                if any(tt in assigned_tasks for tt in c[0]):
                    continue
                if c[2] < best_score:
                    best_score = c[2]
                    best = c
                break
        if best is None:
            break
        assigned_couriers.add(best[1])
        assigned_tasks.update(best[0])
        result.append((",".join(best[0]), [best[1]]))
    return result
