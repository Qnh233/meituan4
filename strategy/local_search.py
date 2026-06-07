"""局部搜索策略：模拟退火 + 禁忌搜索。

纯 Python 标准库实现，在解空间做邻域搜索。
优化：带时间预算感知，确保 ≤ 8 秒。
"""

import random
import time
import math
from strategy.base import BaseStrategy, register
from parser import ProblemData


def _build_index(data: ProblemData) -> dict[tuple[str, str], float]:
    """预建 (task_ids_str, courier_id) -> score 索引加速查找。"""
    idx = {}
    for c in data.candidates:
        key = (",".join(c.task_ids), c.courier_id)
        idx[key] = c.total_score
    return idx


def _plan_score_fast(plan: list, fast_index: dict, total_tasks: int) -> tuple[float, float]:
    """快速评分：用预建索引避免 get_candidate 调用。"""
    covered = set()
    total = 0.0
    for task_str, courier_list in plan:
        task_ids = tuple(t.strip() for t in task_str.split(","))
        for cid in courier_list:
            score = fast_index.get((task_str, cid))
            if score is not None:
                covered.update(task_ids)
                total += score
                break
    cov = len(covered) / total_tasks if total_tasks > 0 else 0
    return cov, total


def _random_solution(data: ProblemData, rng: random.Random,
                     fast_index: dict | None = None) -> list[tuple[str, list[str]]]:
    """随机生成一个可行解（洗牌后贪心）。"""
    valid = [c for c in data.candidates if c.willingness > 0]
    rng.shuffle(valid)
    assigned_couriers = set()
    assigned_tasks = set()
    result = []
    for c in valid:
        if c.courier_id in assigned_couriers:
            continue
        if any(t in assigned_tasks for t in c.task_ids):
            continue
        assigned_couriers.add(c.courier_id)
        assigned_tasks.update(c.task_ids)
        result.append((",".join(c.task_ids), [c.courier_id]))
    return result


def _random_neighbor(plan: list, valid_cands: list, assigned_couriers: set,
                     assigned_tasks: set, rng: random.Random) -> list:
    """生成邻域解：替换/交换/增减一个分配（原地修改列表避免大量拷贝）。"""
    new_plan = list(plan)
    op = rng.randint(0, 2)

    if op == 0 and len(new_plan) > 0 and valid_cands:
        idx = rng.randint(0, len(new_plan) - 1)
        new_cand = rng.choice(valid_cands)
        new_plan[idx] = (",".join(new_cand.task_ids), [new_cand.courier_id])

    elif op == 1 and len(new_plan) > 1:
        i, j = rng.sample(range(len(new_plan)), 2)
        new_plan[i], new_plan[j] = new_plan[j], new_plan[i]

    else:
        if rng.random() < 0.5 and len(new_plan) > 1:
            idx = rng.randint(0, len(new_plan) - 1)
            new_plan.pop(idx)
        elif valid_cands:
            new_cand = rng.choice(valid_cands)
            new_plan.append((",".join(new_cand.task_ids), [new_cand.courier_id]))

    return new_plan


def _repair_plan(plan: list[tuple[str, list[str]]],
                fast_index: dict) -> list[tuple[str, list[str]]]:
    """修复方案：去重骑手和任务，按顺序保留。"""
    seen_couriers = set()
    seen_tasks = set()
    result = []
    for task_str, courier_list in plan:
        task_ids = tuple(t.strip() for t in task_str.split(","))
        valid_couriers = [c for c in courier_list if c not in seen_couriers]
        if not valid_couriers:
            continue
        if any(t in seen_tasks for t in task_ids):
            continue
        seen_couriers.add(valid_couriers[0])
        seen_tasks.update(task_ids)
        result.append((task_str, [valid_couriers[0]]))
    return result


@register(name="SimulatedAnnealing")
class SimulatedAnnealing(BaseStrategy):
    """模拟退火：带时间预算，≤8秒。"""

    name = "SimulatedAnnealing"
    description = "模拟退火局部搜索，初始温度500，≤8s自适应迭代"

    def solve(self, data: ProblemData) -> list[tuple[str, list[str]]]:
        fast_idx = _build_index(data)
        valid_cands = [c for c in data.candidates if c.willingness > 0]
        total_tasks = len(data.all_tasks)
        rng = random.Random(42)

        current = _random_solution(data, rng, fast_idx)
        current_cov, current_score = _plan_score_fast(current, fast_idx, total_tasks)
        current_obj = current_cov * 100 - current_score / 1000

        best = list(current)
        best_obj = current_obj

        temp = 500.0
        deadline = time.perf_counter() + 7.5
        iteration = 0

        while time.perf_counter() < deadline:
            neighbor = _random_neighbor(current, valid_cands, set(), set(), rng)
            neighbor = _repair_plan(neighbor, fast_idx)
            if not neighbor:
                continue
            n_cov, n_score = _plan_score_fast(neighbor, fast_idx, total_tasks)
            n_obj = n_cov * 100 - n_score / 1000

            delta = n_obj - current_obj
            if delta > 0 or rng.random() < math.exp(delta / max(temp, 0.001)):
                current = neighbor
                current_obj = n_obj
                if current_obj > best_obj:
                    best = list(current)
                    best_obj = current_obj

            temp *= 0.998
            iteration += 1

        repaired = _repair_plan(best, fast_idx)
        return repaired if repaired else _random_solution(data, rng, fast_idx)


@register(name="TabuSearch")
class TabuSearch(BaseStrategy):
    """禁忌搜索：带时间预算，≤8秒。"""

    name = "TabuSearch"
    description = "禁忌搜索，tabu_size=30，≤8s自适应迭代"

    def solve(self, data: ProblemData) -> list[tuple[str, list[str]]]:
        fast_idx = _build_index(data)
        valid_cands = [c for c in data.candidates if c.willingness > 0]
        total_tasks = len(data.all_tasks)
        rng = random.Random(42)

        current = _random_solution(data, rng, fast_idx)
        current_cov, current_score = _plan_score_fast(current, fast_idx, total_tasks)
        current_obj = current_cov * 100 - current_score / 1000

        best = list(current)
        best_obj = current_obj

        tabu_set: set[frozenset] = set()
        tabu_size = 30
        deadline = time.perf_counter() + 7.5

        while time.perf_counter() < deadline:
            best_n_obj = float("-inf")
            best_neighbor = None

            for _ in range(15):
                neighbor = _random_neighbor(current, valid_cands, set(), set(), rng)
                neighbor = _repair_plan(neighbor, fast_idx)
                if not neighbor:
                    continue
                key = frozenset((t, tuple(c)) for t, c in neighbor)
                if key in tabu_set:
                    continue
                n_cov, n_score = _plan_score_fast(neighbor, fast_idx, total_tasks)
                n_obj = n_cov * 100 - n_score / 1000
                if n_obj > best_n_obj:
                    best_n_obj = n_obj
                    best_neighbor = neighbor

            if best_neighbor is None:
                continue

            current = best_neighbor
            current_obj = best_n_obj
            tabu_set.add(frozenset((t, tuple(c)) for t, c in current))
            if len(tabu_set) > tabu_size:
                # 移除最旧: Python set 不支持有序，用 approximate
                tabu_set = set(list(tabu_set)[1:])

            if current_obj > best_obj:
                best = list(current)
                best_obj = current_obj

        repaired = _repair_plan(best, fast_idx)
        return repaired if repaired else _random_solution(data, rng, fast_idx)
