# Strategy: ScarcityFirstCostEfficient
# Description: Prioritize matches that cover the most scarce orders and have low cost, using a greedy approach.
def solve(input_text: str) -> list:
    lines = input_text.strip().split('\n')
    matches = []
    for line in lines:
        parts = line.split('\t')
        if len(parts) < 4:
            continue
        task_id_list_str = parts[0].strip()
        courier_id = parts[1].strip()
        try:
            score = float(parts[2].strip())
        except:
            score = 0.0
        try:
            willingness = float(parts[3].strip())
        except:
            willingness = 0.0
        task_ids = set(task.strip() for task in task_id_list_str.split(',') if task.strip())
        if not task_ids:
            continue
        matches.append((task_ids, courier_id, score, task_id_list_str))
    if not matches:
        return []
    order_to_matches = {}
    for idx, (task_ids, _, _, _) in enumerate(matches):
        for task_id in task_ids:
            if task_id not in order_to_matches:
                order_to_matches[task_id] = []
            order_to_matches[task_id].append(idx)
    scarcity = {task_id: len(order_to_matches[task_id]) for task_id in order_to_matches}
    match_scarcity = []
    for idx, (task_ids, courier_id, score, _) in enumerate(matches):
        min_scarcity = min(scarcity[task_id] for task_id in task_ids)
        match_scarcity.append((min_scarcity, score, len(task_ids), idx))
    match_scarcity.sort(key=lambda x: (x[0], x[1], -x[2]))
    assigned_couriers = set()
    assigned_tasks = set()
    result = []
    for _, _, _, idx in match_scarcity:
        task_ids, courier_id, score, task_id_list_str = matches[idx]
        if courier_id in assigned_couriers:
            continue
        if task_ids & assigned_tasks:
            continue
        assigned_couriers.add(courier_id)
        assigned_tasks.update(task_ids)
        result.append((task_id_list_str, [courier_id]))
    return result