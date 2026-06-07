# Strategy: WeightedWillingness
# Description: Each order independently assigns to a rider with highest weighted score of willingness and normalized cost.

def solve(input_text: str) -> list:
    orders = []
    max_total_score = 0
    for line in input_text.strip().split('\n')[1:]:
        parts = line.strip().split('\t')
        if len(parts) < 4:
            continue
        task_id_list_str, courier_id, total_score_str, willingness_str = parts[0], parts[1], parts[2], parts[3]
        total_score = float(total_score_str)
        willingness = float(willingness_str)
        if total_score > max_total_score:
            max_total_score = total_score
        orders.append((task_id_list_str, courier_id, total_score, willingness))
    
    if max_total_score == 0:
        max_total_score = 1
    
    lambda_factor = 0.5 / max_total_score
    
    best_assignment = {}
    for task_id_list_str, courier_id, total_score, willingness in orders:
        score = willingness - lambda_factor * total_score
        if task_id_list_str not in best_assignment or score > best_assignment[task_id_list_str][1]:
            best_assignment[task_id_list_str] = (courier_id, score)
    
    result = [(task_id_list_str, [courier_id]) for task_id_list_str, (courier_id, _) in best_assignment.items()]
    return result