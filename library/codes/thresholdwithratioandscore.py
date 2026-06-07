# Strategy: ThresholdWithRatioAndScore
# Description: Two-phase assignment: high willingness first, then ratio-optimized allocation for remaining
def solve(input_text: str) -> list:
    lines = input_text.strip().split('\n')
    records = []
    for line in lines[1:]:
        parts = line.strip().split('\t')
        task_ids = parts[0].split(',')
        courier_id = parts[1]
        score = float(parts[2])
        willingness = float(parts[3])
        records.append((task_ids, courier_id, score, willingness))
    
    # Phase 1: High willingness assignments (threshold 0.7)
    high_threshold = 0.7
    high_willing = [r for r in records if r[3] >= high_threshold]
    high_willing.sort(key=lambda x: (-x[3], x[2]))
    
    assigned_tasks = set()
    assigned_couriers = set()
    assignments = []
    
    for task_ids, courier_id, score, willingness in high_willing:
        if courier_id in assigned_couriers:
            continue
        tasks_available = [t for t in task_ids if t not in assigned_tasks]
        if tasks_available:
            task_str = ','.join(tasks_available)
            assignments.append((task_str, [courier_id]))
            assigned_tasks.update(tasks_available)
            assigned_couriers.add(courier_id)
    
    # Phase 2: Remaining assignments with ratio optimization
    remaining = [r for r in records if r[3] < high_threshold and r[1] not in assigned_couriers]
    
    # Calculate ratio: willingness/score (higher is better)
    for i in range(len(remaining)):
        task_ids, courier_id, score, willingness = remaining[i]
        ratio = willingness / score if score > 0 else willingness * 1000
        remaining[i] = (task_ids, courier_id, score, willingness, ratio)
    
    remaining.sort(key=lambda x: (-x[4]))
    
    for task_ids, courier_id, score, willingness, ratio in remaining:
        if courier_id in assigned_couriers:
            continue
        tasks_available = [t for t in task_ids if t not in assigned_tasks]
        if tasks_available:
            task_str = ','.join(tasks_available)
            assignments.append((task_str, [courier_id]))
            assigned_tasks.update(tasks_available)
            assigned_couriers.add(courier_id)
    
    return assignments