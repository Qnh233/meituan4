# Strategy: ScoreOptimized
# Description: 成本优化：按 unit_score 升序，但跳过 willingness<0.1 的候选

def solve(input_text: str) -> list:
    lines = input_text.strip().splitlines()
    if not lines:
        return []
    start = 1 if lines[0].startswith("task_id_list") else 0
    candidates = []
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
    candidates.sort(key=lambda x: x[2] / len(x[0]) if len(x[0]) > 0 else float('inf'))
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
