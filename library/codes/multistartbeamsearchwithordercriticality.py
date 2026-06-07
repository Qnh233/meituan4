def solve(input_text):
    # 简单的线性同余生成器，替代 random 模块
    random_state = 1
    def random_seed(seed):
        nonlocal random_state
        random_state = seed % 2147483647
        if random_state <= 0:
            random_state += 2147483646
    def random_random():
        nonlocal random_state
        random_state = (random_state * 1103515245 + 12345) % 2147483647
        return (random_state & 0x7fffffff) / 2147483647.0
    def random_uniform(a, b):
        return a + (b - a) * random_random()
    
    # 堆操作函数，替代 heapq 模块
    def heap_push(heap, item):
        heap.append(item)
        i = len(heap) - 1
        while i > 0:
            parent = (i - 1) // 2
            if heap[parent] > heap[i]:
                heap[parent], heap[i] = heap[i], heap[parent]
                i = parent
            else:
                break
    def heap_replace(heap, item):
        if not heap:
            heap.append(item)
            return None
        min_item = heap[0]
        heap[0] = item
        i = 0
        n = len(heap)
        while True:
            left = 2 * i + 1
            right = 2 * i + 2
            smallest = i
            if left < n and heap[left] < heap[smallest]:
                smallest = left
            if right < n and heap[right] < heap[smallest]:
                smallest = right
            if smallest != i:
                heap[i], heap[smallest] = heap[smallest], heap[i]
                i = smallest
            else:
                break
        return min_item
    
    # 解析输入
    lines = input_text.strip().split('\n')
    candidates = []
    order_set = set()
    
    for line in lines:
        if not line.strip():
            continue
        parts = line.split(',')
        if len(parts) < 4:
            continue
        task_id_list_str = parts[0].strip()
        try:
            courier_id = int(parts[1].strip())
            total_score = float(parts[2].strip())
            willingness = float(parts[3].strip())
        except (ValueError, IndexError):
            continue
        if willingness <= 0:
            continue
        task_ids = []
        for tid in task_id_list_str.split(','):
            tid = tid.strip()
            if tid:
                task_ids.append(tid)
                order_set.add(tid)
        if task_ids:
            candidates.append({
                'task_ids': task_ids,
                'courier_id': courier_id,
                'total_score': total_score,
                'willingness': willingness,
                'task_set': frozenset(task_ids)
            })
    
    if not candidates or not order_set:
        return []
    
    # 按订单覆盖分组
    order_to_candidates = {}
    for cand in candidates:
        for tid in cand['task_ids']:
            if tid not in order_to_candidates:
                order_to_candidates[tid] = []
            order_to_candidates[tid].append(cand)
    
    # 计算订单关键性
    order_criticality = {}
    for order in order_set:
        order_criticality[order] = len(order_to_candidates[order])
    
    # Beam search 参数
    BEAM_WIDTH = 50
    MAX_RESTARTS = 20
    
    best_solution = None
    best_score = float('inf')
    
    for restart in range(MAX_RESTARTS):
        random_seed(restart * 123 + 42)
        criticality_weight = random_uniform(0.5, 2.0)
        score_weight = random_uniform(0.5, 2.0)
        coverage_weight = random_uniform(0.5, 2.0)
        
        # Beam search 状态：(score, covered_orders, used_couriers, selected_candidates)
        beam = []
        initial_state = (0.0, set(), set(), [])
        heap_push(beam, initial_state)
        
        # 按关键性加权分数排序候选
        processed_candidates = sorted(candidates, key=lambda x: (
            -criticality_weight * min(order_criticality[t] for t in x['task_ids']),
            score_weight * x['total_score'],
            -coverage_weight * len(x['task_ids'])
        ))
        
        # Beam search
        while beam:
            next_beam = []
            
            for score, covered, couriers, selected in beam:
                if covered == order_set:
                    if score < best_score:
                        best_score = score
                        best_solution = (selected[:], couriers.copy(), covered.copy())
                    continue
                
                for cand in processed_candidates:
                    if cand['courier_id'] in couriers:
                        continue
                    new_tasks = set(cand['task_ids']) - covered
                    if not new_tasks:
                        continue
                    new_score = score + cand['total_score']
                    new_covered = covered | set(cand['task_ids'])
                    new_couriers = couriers | {cand['courier_id']}
                    new_selected = selected + [(cand['task_ids'], [cand['courier_id']])]
                    state = (new_score, new_covered, new_couriers, new_selected)
                    
                    if len(next_beam) < BEAM_WIDTH:
                        heap_push(next_beam, state)
                    elif new_score < next_beam[-1][0]:
                        heap_replace(next_beam, state)
            
            beam = next_beam
            if not beam:
                break
        
        if best_solution:
            break
    
    # 如果没有完整解，进行两阶段修复
    if not best_solution:
        covered = set()
        used_couriers = set()
        selected = []
        total_score = 0.0
        
        sorted_candidates = sorted(candidates, key=lambda x: (
            -min(order_criticality[t] for t in x['task_ids']),
            x['total_score'] / len(x['task_ids'])
        ))
        
        for cand in sorted_candidates:
            if cand['courier_id'] in used_couriers:
                continue
            new_tasks = set(cand['task_ids']) - covered
            if new_tasks:
                selected.append((cand['task_ids'], [cand['courier_id']]))
                used_couriers.add(cand['courier_id'])
                covered.update(cand['task_ids'])
                total_score += cand['total_score']
                if covered == order_set:
                    break
        
        if covered != order_set:
            missing = order_set - covered
            backup_candidates = []
            for cand in candidates:
                if cand['courier_id'] in used_couriers:
                    continue
                cand_tasks = set(cand['task_ids'])
                if cand_tasks & missing:
                    backup_candidates.append(cand)
            
            backup_candidates.sort(key=lambda x: (
                -len(set(x['task_ids']) & missing),
                x['total_score']
            ))
            
            for cand in backup_candidates:
                if used_couriers and len(used_couriers) >= len(order_set) // 2 + 3:
                    break
                cand_tasks = set(cand['task_ids'])
                if cand_tasks & missing:
                    selected.append((cand['task_ids'], [cand['courier_id']]))
                    used_couriers.add(cand['courier_id'])
                    covered.update(cand_tasks)
                    total_score += cand['total_score']
                    missing = order_set - covered
                    if not missing:
                        break
        
        best_solution = (selected, used_couriers, covered)
    
    # 格式化输出
    if best_solution:
        selected_candidates, _, _ = best_solution
        result = []
        for task_ids, courier_ids in selected_candidates:
            task_id_list_str = ','.join(task_ids)
            result.append((task_id_list_str, courier_ids))
        return result
    else:
        return []