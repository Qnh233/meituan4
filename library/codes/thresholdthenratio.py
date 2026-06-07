# Strategy: ThresholdThenRatio
# Description: Two-phase strategy: first assign high-willingness pairs by score, then assign remaining by score/willingness ratio
def solve(input_text: str) -> list:
    lines = input_text.strip().split('\n')
    if not lines:
        return []
    
    entries = []
    for line in lines[1:]:
        parts = line.strip().split('\t')
        if len(parts) != 4:
            continue
        task_id_list_str, courier_id, total_score_str, willingness_str = parts
        total_score = float(total_score_str)
        willingness = float(willingness_str)
        entries.append((task_id_list_str, courier_id, total_score, willingness))
    
    if not entries:
        return []
    
    # Phase 1: High willingness threshold
    threshold = 0.7
    high_willing = [(t, c, s, w) for t, c, s, w in entries if w >= threshold]
    low_willing = [(t, c, s, w) for t, c, s, w in entries if w < threshold]
    
    # Sort by score for high willingness
    high_willing.sort(key=lambda x: x[2])
    
    # Sort by ratio for low willingness
    for i in range(len(low_willing)):
        t, c, s, w = low_willing[i]
        ratio = s / w if w > 0 else float('inf')
        low_willing[i] = (t, c, s, w, ratio)
    low_willing.sort(key=lambda x: x[4])
    
    assigned_tasks = set()
    assigned_couriers = set()
    result = []
    
    # Assign high willingness first
    for task_str, courier_id, score, w in high_willing:
        if task_str in assigned_tasks or courier_id in assigned_couriers:
            continue
        result.append((task_str, [courier_id]))
        assigned_tasks.add(task_str)
        assigned_couriers.add(courier_id)
    
    # Assign low willingness by ratio
    for task_str, courier_id, score, w, ratio in low_willing:
        if task_str in assigned_tasks or courier_id in assigned_couriers:
            continue
        result.append((task_str, [courier_id]))
        assigned_tasks.add(task_str)
        assigned_couriers.add(courier_id)
    
    return result