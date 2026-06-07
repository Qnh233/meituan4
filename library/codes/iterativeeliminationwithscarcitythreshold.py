# Strategy: IterativeEliminationWithScarcityThreshold
# Description: Iteratively removes matched resources, with scarcity-aware thresholding and cost-willingness ratio
def solve(input_text: str) -> list:
    import re
    
    lines = input_text.strip().split('\n')
    header = lines[0].split('\t')
    task_idx = header.index('task_id_list')
    courier_idx = header.index('courier_id')
    score_idx = header.index('total_score')
    will_idx = header.index('willingness')
    
    data = []
    for line in lines[1:]:
        parts = line.split('\t')
        task_ids = parts[task_idx].split(',')
        courier_id = parts[courier_idx]
        score = float(parts[score_idx])
        willingness = float(parts[will_idx])
        data.append((task_ids, courier_id, score, willingness))
    
    task_to_options = {}
    courier_to_tasks = {}
    for task_ids, courier_id, score, willingness in data:
        key = tuple(sorted(task_ids))
        if key not in task_to_options:
            task_to_options[key] = []
        task_to_options[key].append((courier_id, score, willingness))
        if courier_id not in courier_to_tasks:
            courier_to_tasks[courier_id] = []
        courier_to_tasks[courier_id].append((key, score, willingness))
    
    assigned_tasks = set()
    assigned_couriers = set()
    result = []
    
    for _ in range(100):
        if len(assigned_tasks) == len(task_to_options) or len(assigned_couriers) == len(courier_to_tasks):
            break
        
        available_tasks = [t for t in task_to_options if t not in assigned_tasks]
        available_couriers = [c for c in courier_to_tasks if c not in assigned_couriers]
        
        scarcity = {}
        for task in available_tasks:
            count = sum(1 for opt in task_to_options[task] if opt[0] in available_couriers)
            scarcity[task] = count
        
        candidates = []
        for task in available_tasks:
            for courier_id, score, willingness in task_to_options[task]:
                if courier_id in available_couriers and willingness > 0.3:
                    scarcity_factor = 1.0 / (scarcity[task] + 0.1)
                    ratio = (willingness * scarcity_factor) / (score + 0.1)
                    candidates.append((ratio, score, willingness, task, courier_id))
        
        if not candidates:
            break
        
        candidates.sort(key=lambda x: (-x[0], x[1], -x[2]))
        
        matched_tasks_this_round = set()
        matched_couriers_this_round = set()
        
        for ratio, score, willingness, task, courier_id in candidates:
            if task not in matched_tasks_this_round and courier_id not in matched_couriers_this_round:
                matched_tasks_this_round.add(task)
                matched_couriers_this_round.add(courier_id)
                result.append((','.join(sorted(task)), [courier_id]))
                assigned_tasks.add(task)
                assigned_couriers.add(courier_id)
        
        if not matched_tasks_this_round:
            break
    
    return result