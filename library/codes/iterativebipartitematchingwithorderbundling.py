# Strategy: IterativeBipartiteMatchingWithOrderBundling
# Description: Reformulates as a series of weighted bipartite matchings by decomposing 3-order bundles into 2-order connections, iteratively improving via local swaps and covering unassigned orders with a greedy fallback.

import sys
import time
import math
from collections import defaultdict, Counter
from typing import List, Tuple, Dict, Set, Optional
import heapq
import itertools

def solve(input_text: str) -> list:
    """
    Solve using iterative bipartite matching + order bundling decomposition.
    """
    lines = input_text.strip().split('\n')
    if not lines:
        return []
    
    # Parse input - handle possible header
    records = []
    for line in lines:
        parts = line.strip().split('\t')
        if len(parts) < 3:
            continue
        try:
            task_id_str = parts[0].strip()
            courier_id = parts[1].strip()
            willingness = float(parts[2].strip())
            total_score = float(parts[3].strip()) if len(parts) > 3 else 0.0
            records.append({
                'task_id_str': task_id_str,
                'courier_id': courier_id,
                'willingness': willingness,
                'total_score': total_score
            })
        except (ValueError, IndexError):
            continue
    
    if not records:
        return []
    
    # Filter records with willingness > 0
    valid_records = [r for r in records if r['willingness'] > 0]
    if not valid_records:
        return []
    
    # Build order and courier mappings
    all_orders = set()
    all_couriers = set()
    for r in valid_records:
        order_ids = r['task_id_str'].split(',')
        for oid in order_ids:
            all_orders.add(oid.strip())
        all_couriers.add(r['courier_id'])
    
    # Build candidate lists per courier
    courier_candidates: Dict[str, List[dict]] = defaultdict(list)
    for r in valid_records:
        courier_candidates[r['courier_id']].append(r)
    
    # Build candidate lists per order
    order_candidates: Dict[str, List[dict]] = defaultdict(list)
    for r in valid_records:
        order_ids = r['task_id_str'].split(',')
        for oid in order_ids:
            order_candidates[oid.strip()].append(r)
    
    # Phase 1: Greedy assignment for initial solution
    assigned_orders: Set[str] = set()
    assigned_couriers: Set[str] = set()
    assignment: List[Tuple[str, str]] = []  # (task_id_str, courier_id)
    
    # Sort orders by number of available candidates (rarest first)
    order_rarity = {}
    for o in all_orders:
        candidates = order_candidates.get(o, [])
        # Filter out candidates that use already assigned orders
        viable = []
        for c in candidates:
            order_ids = c['task_id_str'].split(',')
            clean_ids = [oid.strip() for oid in order_ids]
            if all(oid not in assigned_orders for oid in clean_ids):
                viable.append(c)
        order_rarity[o] = len(viable)
    
    # Sort unassigned orders by rarity
    unassigned_orders = sorted(all_orders, key=lambda o: order_rarity.get(o, 0))
    
    # Greedy assignment
    for order in unassigned_orders:
        if order in assigned_orders:
            continue
        
        # Find best candidate for this order
        candidates = order_candidates.get(order, [])
        best_candidate = None
        best_score = float('inf')
        
        for c in candidates:
            order_ids = c['task_id_str'].split(',')
            clean_ids = [oid.strip() for oid in order_ids]
            
            # Check if all orders and courier are available
            if any(oid in assigned_orders for oid in clean_ids):
                continue
            if c['courier_id'] in assigned_couriers:
                continue
            
            if c['total_score'] < best_score:
                best_score = c['total_score']
                best_candidate = c
        
        if best_candidate:
            order_ids = best_candidate['task_id_str'].split(',')
            clean_ids = [oid.strip() for oid in order_ids]
            for oid in clean_ids:
                assigned_orders.add(oid)
            assigned_couriers.add(best_candidate['courier_id'])
            assignment.append((best_candidate['task_id_str'], best_candidate['courier_id']))
    
    # Phase 2: Iterative improvement via order swaps
    # Build current assignment map
    order_to_courier: Dict[str, str] = {}
    for task_str, courier_id in assignment:
        order_ids = task_str.split(',')
        for oid in order_ids:
            order_to_courier[oid.strip()] = courier_id
    
    # Try to improve by unbundling and rebundling
    improved = True
    max_iterations = 20
    iteration = 0
    
    while improved and iteration < max_iterations:
        improved = False
        iteration += 1
        
        # Get current assignment as list of (task_id_str, courier_id)
        current_assignment = list(assignment)
        
        # For each assigned courier, check if we can find a better bundle
        for i, (task_str, courier_id) in enumerate(current_assignment):
            order_ids = task_str.split(',')
            clean_ids = [oid.strip() for oid in order_ids]
            
            # Get all candidates for this courier
            courier_cands = courier_candidates.get(courier_id, [])
            
            for c in courier_cands:
                if c['task_id_str'] == task_str:
                    continue  # Same bundle, skip
                
                cand_order_ids = c['task_id_str'].split(',')
                cand_clean_ids = [oid.strip() for oid in cand_order_ids]
                
                # Check if we can switch to this bundle
                # All orders in new bundle must be currently assigned to this courier
                # OR unassigned (but that would break coverage)
                all_belong_to_courier = True
                for oid in cand_clean_ids:
                    if oid not in order_to_courier or order_to_courier[oid] != courier_id:
                        all_belong_to_courier = False
                        break
                
                if not all_belong_to_courier:
                    continue
                
                # Check if new bundle has lower score
                current_score = sum(
                    r['total_score'] for r in courier_candidates.get(courier_id, [])
                    if r['task_id_str'] == task_str
                )
                
                if c['total_score'] < current_score:
                    # Update assignment
                    assignment[i] = (c['task_id_str'], courier_id)
                    # Update order_to_courier mapping
                    for oid in clean_ids:
                        if oid in order_to_courier:
                            del order_to_courier[oid]
                    for oid in cand_clean_ids:
                        order_to_courier[oid] = courier_id
                    improved = True
                    break
            
            if improved:
                break
        
        if not improved:
            # Try swapping orders between couriers
            for i in range(len(current_assignment)):
                for j in range(i + 1, len(current_assignment)):
                    task_str_i, courier_i = current_assignment[i]
                    task_str_j, courier_j = current_assignment[j]
                    
                    if courier_i == courier_j:
                        continue
                    
                    order_ids_i = task_str_i.split(',')
                    order_ids_j = task_str_j.split(',')
                    clean_i = [oid.strip() for oid in order_ids_i]
                    clean_j = [oid.strip() for oid in order_ids_j]
                    
                    # Try to find a candidate that covers orders from both bundles
                    # This is complex, so just check if we can reassign one courier
                    # to handle orders from the other
                    cands_i = courier_candidates.get(courier_i, [])
                    cands_j = courier_candidates.get(courier_j, [])
                    
                    # Check if courier_i can take order_ids_j
                    for c in cands_i:
                        cand_oids = c['task_id_str'].split(',')
                        cand_clean = [oid.strip() for oid in cand_oids]
                        if set(cand_clean) == set(clean_j):
                            # Check if this improves total score
                            score_j = None
                            for r in valid_records:
                                if r['task_id_str'] == task_str_j and r['courier_id'] == courier_j:
                                    score_j = r['total_score']
                                    break
                            if score_j and c['total_score'] < score_j:
                                # Swap: courier_i takes order_ids_j, courier_j takes order_ids_i
                                # First check if courier_j can take order_ids_i
                                for c2 in cands_j:
                                    cand_oids2 = c2['task_id_str'].split(',')
                                    cand_clean2 = [oid.strip() for oid in cand_oids2]
                                    if set(cand_clean2) == set(clean_i):
                                        score_i = None
                                        for r in valid_records:
                                            if r['task_id_str'] == task_str_i and r['courier_id'] == courier_i:
                                                score_i = r['total_score']
                                                break
                                        if score_i and (c['total_score'] + c2['total_score']) < (score_i + score_j):
                                            # Perform swap
                                            assignment[i] = (c['task_id_str'], courier_i)
                                            assignment[j] = (c2['task_id_str'], courier_j)
                                            for oid in clean_i:
                                                if oid in order_to_courier:
                                                    del order_to_courier[oid]
                                            for oid in clean_j:
                                                if oid in order_to_courier:
                                                    del order_to_courier[oid]
                                            for oid in cand_clean:
                                                order_to_courier[oid] = courier_i
                                            for oid in cand_clean2:
                                                order_to_courier[oid] = courier_j
                                            improved = True
                                            break
                                if improved:
                                    break
                    if improved:
                        break
                if improved:
                    break
    
    # Phase 3: Handle unassigned orders (if any)
    # This shouldn't happen if all orders can be covered, but just in case
    all_assigned_now = set()
    for task_str, _ in assignment:
        for oid in task_str.split(','):
            all_assigned_now.add(oid.strip())
    
    missing_orders = all_orders - all_assigned_now
    if missing_orders:
        # Try to find single-order assignments for missing orders
        for oid in missing_orders:
            # Find a candidate that covers just this order
            candidates = order_candidates.get(oid, [])
            single_order_cands = [c for c in candidates if len(c['task_id_str'].split(',')) == 1]
            
            best_candidate = None
            best_score = float('inf')
            for c in single_order_cands:
                if c['courier_id'] in assigned_couriers:
                    continue
                if c['total_score'] < best_score:
                    best_score = c['total_score']
                    best_candidate = c
            
            if best_candidate:
                assigned_orders.add(oid)
                assigned_couriers.add(best_candidate['courier_id'])
                assignment.append((best_candidate['task_id_str'], best_candidate['courier_id']))
    
    # Format output
    result = []
    for task_str, courier_id in assignment:
        result.append((task_str, [courier_id]))
    
    return result