# Strategy: ThresholdThenRatioByScore
# Description: Prioritize high-willingness couriers by score, low-willingness by cost-efficiency ratio
def solve(input_text: str) -> list:
    lines = input_text.strip().split('\n')
    if not lines:
        return []
    
    # Parse data
    entries = []
    for line in lines[1:]:  # Skip header if present
        parts = line.strip().split('\t')
        if len(parts) < 4:
            continue
        task_ids = parts[0].strip()
        courier = parts[1].strip()
        try:
            score = float(parts[2])
            willingness = float(parts[3])
        except:
            continue
        entries.append((task_ids, courier, score, willingness))
    
    # Separate into high and low willingness groups
    threshold = 0.7
    high_group = []
    low_group = []
    for task_ids, courier, score, willingness in entries:
        if willingness >= threshold:
            high_group.append((task_ids, courier, score, willingness))
        else:
            # Handle zero willingness to avoid division by zero
            ratio = score / willingness if willingness > 0 else float('inf')
            low_group.append((task_ids, courier, score, willingness, ratio))
    
    # Sort groups: high by score ascending, low by ratio ascending
    high_group.sort(key=lambda x: x[2])
    low_group.sort(key=lambda x: x[4])
    
    # Greedy assignment
    assigned_tasks = set()
    assigned_couriers = set()
    result = []
    
    # Assign high willingness group first
    for task_ids, courier, score, willingness in high_group:
        if task_ids not in assigned_tasks and courier not in assigned_couriers:
            result.append((task_ids, [courier]))
            assigned_tasks.add(task_ids)
            assigned_couriers.add(courier)
    
    # Assign low willingness group
    for task_ids, courier, score, willingness, ratio in low_group:
        if task_ids not in assigned_tasks and courier not in assigned_couriers:
            result.append((task_ids, [courier]))
            assigned_tasks.add(task_ids)
            assigned_couriers.add(courier)
    
    return result