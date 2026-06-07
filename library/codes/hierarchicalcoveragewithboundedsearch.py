# Strategy: HierarchicalCoverageWithBoundedSearch
# Description: 结合订单稀缺度引导的层次化覆盖与有限深度束搜索，在保证确定性全覆盖的前提下最小化总成本

```python
import sys
import time
from collections import defaultdict, deque
from typing import List, Tuple, Dict, Set
import random

def solve(input_text: str) -> list:
    """
    分层覆盖+束搜索策略：
    1. 构建候选池，过滤willingness<=0
    2. 计算订单稀缺度（可用骑手数）
    3. 稀缺订单优先强制匹配
    4. 对剩余订单使用束搜索寻找低成本组合
    5. 贪婪修复未覆盖订单
    """
    # 解析输入
    lines = input_text.strip().split('\n')
    if not lines:
        return []
    
    candidates = []
    header_skipped = False
    
    for line in lines:
        parts = line.strip().split()
        if not parts:
            continue
        # 跳过可能的header行
        if parts[0] == 'task_id_list' or parts[0].startswith('task'):
            if not header_skipped:
                header_skipped = True
                continue
        
        if len(parts) < 4:
            continue
        
        task_id_list_str = parts[0]
        courier_id = parts[1]
        
        try:
            willingness = float(parts[2])
            total_score = float(parts[3])
        except (ValueError, IndexError):
            continue
        
        # 过滤willingness<=0的候选
        if willingness <= 0:
            continue
        
        # 解析订单列表
        order_ids = [oid.strip() for oid in task_id_list_str.split(',') if oid.strip()]
        if not order_ids:
            continue
        
        candidates.append({
            'tasks': task_id_list_str,
            'order_ids': order_ids,
            'courier': courier_id,
            'score': total_score,
            'willingness': willingness,
            'num_orders': len(order_ids)
        })
    
    if not candidates:
        return []
    
    # 收集所有订单和骑手
    all_orders = set()
    all_couriers = set()
    for c in candidates:
        for oid in c['order_ids']:
            all_orders.add(oid)
        all_couriers.add(c['courier'])
    
    # 构建订单到候选的索引
    order_to_candidates = defaultdict(list)
    courier_to_candidates = defaultdict(list)
    for idx, c in enumerate(candidates):
        for oid in c['order_ids']:
            order_to_candidates[oid].append(idx)
        courier_to_candidates[c['courier']].append(idx)
    
    # 计算订单稀缺度（可用骑手数）
    order_scarcity = {}
    for oid in all_orders:
        order_scarcity[oid] = len(order_to_candidates[oid])
    
    # ========== 阶段1：稀缺订单优先强制匹配 ==========
    assigned_couriers = set()
    covered_orders = set()
    result = []
    
    # 按稀缺度升序处理（最稀缺的优先）
    scarce_orders = sorted(all_orders, key=lambda o: order_scarcity.get(o, 0))
    
    for oid in scarce_orders:
        if oid in covered_orders:
            continue
        
        # 找到覆盖此订单且骑手未占用的候选
        best_candidate = None
        best_score = float('inf')
        
        for cidx in order_to_candidates.get(oid, []):
            c = candidates[cidx]
            if c['courier'] in assigned_couriers:
                continue
            # 检查订单是否都已覆盖
            orders_ok = all(o not in covered_orders for o in c['order_ids'])
            if not orders_ok:
                continue
            
            # 优先选稀缺度高的合单
            if c['num_orders'] > 1:
                scarcity_bonus = sum(order_scarcity.get(o, 0) for o in c['order_ids'])
                # 稀缺度加成，鼓励合单
                effective_score = c['score'] - scarcity_bonus * 0.01
            else:
                effective_score = c['score']
            
            if effective_score < best_score:
                best_score = effective_score
                best_candidate = c
        
        if best_candidate:
            # 分配
            for o in best_candidate['order_ids']:
                covered_orders.add(o)
            assigned_couriers.add(best_candidate['courier'])
            result.append((best_candidate['tasks'], [best_candidate['courier']]))
    
    # ========== 阶段2：束搜索处理剩余订单 ==========
    remaining_orders = [o for o in all_orders if o not in covered_orders]
    
    if remaining_orders:
        # 构建剩余候选池
        remaining_candidates = []
        for idx, c in enumerate(candidates):
            if c['courier'] in assigned_couriers:
                continue
            # 检查订单是否可用
            order_available = all(o in remaining_orders or o in covered_orders for o in c['order_ids'])
            if not order_available:
                continue
            # 只保留覆盖未覆盖订单的候选
            if any(o in remaining_orders for o in c['order_ids']):
                remaining_candidates.append(c)
        
        # 束搜索参数
        beam_width = 20
        max_depth = min(len(remaining_orders), 30)
        
        # 状态: (covered_set, assigned_set, score, path)
        # 使用frozenset作为键
        beam = [(frozenset(covered_orders), frozenset(assigned_couriers), 0.0, [])]
        
        for step in range(max_depth):
            new_beam = []
            
            for cov_set, ass_set, score, path in beam:
                # 找未覆盖的订单
                uncovered = [o for o in remaining_orders if o not in cov_set]
                if not uncovered:
                    new_beam.append((cov_set, ass_set, score, path))
                    continue
                
                # 选一个未覆盖订单（按稀缺度）
                target_order = min(uncovered, key=lambda o: order_scarcity.get(o, 0))
                
                # 找覆盖该订单的候选
                valid_candidates = []
                for c in remaining_candidates:
                    if c['courier'] in ass_set:
                        continue
                    if target_order not in c['order_ids']:
                        continue
                    # 检查所有订单是否都可用
                    if any(o not in remaining_orders and o not in cov_set for o in c['order_ids']):
                        continue
                    if any(o in cov_set for o in c['order_ids']):
                        continue
                    valid_candidates.append(c)
                
                if not valid_candidates:
                    continue
                
                # 按score排序，取前beam_width个
                valid_candidates.sort(key=lambda c: c['score'])
                for c in valid_candidates[:beam_width]:
                    new_cov = set(cov_set)
                    for o in c['order_ids']:
                        new_cov.add(o)
                    new_ass = set(ass_set)
                    new_ass.add(c['courier'])
                    new_score = score + c['score']
                    new_path = path + [(c['tasks'], [c['courier']])]
                    new_beam.append((frozenset(new_cov), frozenset(new_ass), new_score, new_path))
            
            if not new_beam:
                break
            
            # 按score排序，保留beam_width个
            new_beam.sort(key=lambda x: x[2])
            beam = new_beam[:beam_width]
        
        # 从束搜索中选最佳结果
        if beam:
            best_beam = min(beam, key=lambda x: x[2])
            # 合并结果
            for tasks, courier_list in best_beam[3]:
                # 检查是否已存在
                existing_tasks = {r[0] for r in result}
                if tasks not in existing_tasks:
                    result.append((tasks, courier_list))
                    for o in tasks.split(','):
                        covered_orders.add(o.strip())
                    assigned_couriers.add(courier_list[0])
    
    # ========== 阶段3：贪婪修复未覆盖订单 ==========
    remaining_orders = [o for o in all_orders if o not in covered_orders]
    
    if remaining_orders:
        # 构建可用候选的优先级队列
        available_candidates = []
        for c in candidates:
            if c['courier'] in assigned_couriers:
                continue
            order_available = all(o in remaining_orders or o in covered_orders for o in c['order_ids'])
            if not order_available:
                continue
            if any(o in remaining_orders for o in c['order_ids']):
                # 计算有效覆盖率
                new_orders = [o for o in c['order_ids'] if o in remaining_orders]
                if new_orders:
                    available_candidates.append((c, len(new_orders)))
        
        # 按覆盖新订单数降序、score升序排序
        available_candidates.sort(key=lambda x: (-x[1], x[0]['score']))
        
        for c, _ in available_candidates:
            if not remaining_orders:
                break
            if c['courier'] in assigned_couriers:
                continue
            # 检查是否覆盖任何未覆盖订单
            covers_new = any(o in remaining_orders for o in c['order_ids'])
            if not covers_new:
                continue
            # 检查订单冲突
            order_conflict = any(o in covered_orders for o in c['order_ids'])
            if order_conflict:
                continue
            
            # 分配
            for o in c['order_ids']:
                covered_orders.add(o)
                if o in remaining_orders:
                    remaining_orders.remove(o)
            assigned_couriers.add(c['courier'])
            result.append((c['tasks'], [c['courier']]))
    
    # ========== 阶段4：最终检查 - 确保覆盖全部订单 ==========
    final_uncovered = [o for o in all_orders if o not in covered_orders]
    
    if final_uncovered:
        # 紧急修复：尝试所有未使用的候选
        used_couriers = set(assigned_couriers)
        for c in candidates:
            if not final_uncovered:
                break
            if c['courier'] in used_couriers:
                continue
            # 检查是否覆盖任何未覆盖订单
            covers_any = any(o in final_uncovered for o in c['order_ids'])
            if not covers_any:
                continue
            # 检查订单冲突
            if any(o in covered_orders for o in c['order_ids']):
                continue
            
            # 分配
            for o in c['order_ids']:
                covered_orders.add(o)
                if o in final_uncovered:
                    final_uncovered.remove(o)
            used_couriers.add(c['courier'])
            result.append((c['tasks'], [c['courier']]))
    
    return result