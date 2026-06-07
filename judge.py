"""本地评测器：双模式（确定性 + 蒙特卡洛），整个 Agent 的"眼睛"。

确定性模式：直接计算覆盖率和总分数（快速，用于策略搜索）。
蒙特卡洛模式：基于 willingness 多次随机模拟（精确，用于最终评估）。
"""

import random
from dataclasses import dataclass

from parser import ProblemData, CandidateAssignment


# 线上惩罚公式反推: penalty ≈ total_score + UNCOVERED_PENALTY × num_uncovered
# 从线上结果估算: scarce_couriers 63%完成率 penalty=2372, 推算每未覆盖任务惩罚≈100-120
UNCOVERED_PENALTY_PER_TASK = 100.0


@dataclass
class EvalResult:
    coverage_rate: float
    total_score: float
    covered_tasks: int
    total_tasks: int
    assigned_count: int
    composite_score: float = 0.0
    estimated_penalty: float = 0.0
    uncovered_tasks: int = 0


def _validate_and_index(
    plan: list[tuple[str, list[str]]],
    data: ProblemData,
) -> tuple[list[tuple[tuple[str, ...], list[str]]], set[str]]:
    """解析并校验方案，返回 [(task_ids_tuple, [courier_id,...]), ...] 和警告集。"""
    parsed = []
    seen_couriers = set()
    seen_task_assignments: dict[str, list[str]] = {}

    for entry in plan:
        if not isinstance(entry, (tuple, list)) or len(entry) != 2:
            continue
        task_id_list_str, courier_list = entry
        if not isinstance(task_id_list_str, str) or not isinstance(courier_list, list):
            continue
        task_ids = tuple(t.strip() for t in task_id_list_str.split(",") if t.strip())
        if not task_ids:
            continue
        valid_couriers = []
        for cid in courier_list:
            if not isinstance(cid, str):
                continue
            cid = cid.strip()
            if cid in seen_couriers:
                continue
            seen_couriers.add(cid)
            valid_couriers.append(cid)

        if not valid_couriers:
            continue

        parsed.append((task_ids, valid_couriers))
        for t in task_ids:
            if t not in seen_task_assignments:
                seen_task_assignments[t] = []
            seen_task_assignments[t].extend(valid_couriers)

    return parsed, seen_task_assignments


def evaluate_deterministic(
    plan: list[tuple[str, list[str]]],
    data: ProblemData,
    *,
    coverage_weight: float = 1.0,
    penalty_weight: float = 1.0,
    max_score: float | None = None,
) -> EvalResult:
    """确定性评测：每条分配必定成功，按 total_score 计入。"""
    parsed, _ = _validate_and_index(plan, data)

    covered_tasks: set[str] = set()
    total_score = 0.0
    assigned_count = 0

    for task_ids, courier_ids in parsed:
        for cid in courier_ids:
            candidate = data.get_candidate(task_ids, cid)
            if candidate is None:
                continue
            assigned_count += 1
            total_score += candidate.total_score
            covered_tasks.update(task_ids)
            break  # 每组 task 只计一次

    total_tasks = len(data.all_tasks)
    coverage_rate = len(covered_tasks) / total_tasks if total_tasks > 0 else 0.0
    uncovered = total_tasks - len(covered_tasks)

    if max_score is None:
        max_score = total_score if total_score > 0 else 1.0

    composite = coverage_weight * coverage_rate - penalty_weight * (total_score / max_score)
    estimated_penalty = total_score + UNCOVERED_PENALTY_PER_TASK * uncovered

    return EvalResult(
        coverage_rate=coverage_rate,
        total_score=total_score,
        covered_tasks=len(covered_tasks),
        total_tasks=total_tasks,
        assigned_count=assigned_count,
        composite_score=composite,
        estimated_penalty=estimated_penalty,
        uncovered_tasks=uncovered,
    )


def evaluate_monte_carlo(
    plan: list[tuple[str, list[str]]],
    data: ProblemData,
    *,
    n_simulations: int = 100,
    coverage_weight: float = 1.0,
    penalty_weight: float = 1.0,
    max_score: float | None = None,
    seed: int = 0,
) -> EvalResult:
    """蒙特卡洛评测：每次模拟中骑手以 willingness 概率接单。"""
    parsed, _ = _validate_and_index(plan, data)
    rng = random.Random(seed)
    total_tasks = len(data.all_tasks)

    coverage_sum = 0
    score_sum = 0.0
    assigned_sum = 0

    for _ in range(n_simulations):
        # 按 task 收集所有接受的分配: task_id -> [(score, assigned)]
        accepted: dict[str, list[tuple[float, str, tuple[str, ...]]]] = {}
        sim_assigned = 0

        for task_ids, courier_ids in parsed:
            for cid in courier_ids:
                candidate = data.get_candidate(task_ids, cid)
                if candidate is None:
                    continue
                if rng.random() < candidate.willingness:
                    sim_assigned += 1
                    for t in task_ids:
                        if t not in accepted:
                            accepted[t] = []
                        accepted[t].append((candidate.total_score, cid, task_ids))

        # 每个 task 取 score 最低的
        sim_covered = set()
        sim_score = 0.0
        # 防止同一 candidate 被重复计分
        scored_candidates: set[tuple[str, tuple[str, ...]]] = set()

        for t in sorted(accepted.keys()):
            best = min(accepted[t], key=lambda x: x[0])
            sim_covered.add(t)
            candidate_key = (best[1], best[2])
            if candidate_key not in scored_candidates:
                scored_candidates.add(candidate_key)
                sim_score += best[0]

        coverage_sum += len(sim_covered)
        score_sum += sim_score
        assigned_sum += sim_assigned

    n = n_simulations
    coverage_rate = (coverage_sum / n) / total_tasks if total_tasks > 0 else 0.0
    avg_score = score_sum / n
    avg_assigned = assigned_sum / n
    avg_covered = coverage_sum / n
    avg_uncovered = total_tasks - avg_covered

    if max_score is None:
        max_score = avg_score if avg_score > 0 else 1.0

    composite = coverage_weight * coverage_rate - penalty_weight * (avg_score / max_score)
    estimated_penalty = avg_score + UNCOVERED_PENALTY_PER_TASK * avg_uncovered

    return EvalResult(
        coverage_rate=coverage_rate,
        total_score=avg_score,
        covered_tasks=int(avg_covered),
        total_tasks=total_tasks,
        assigned_count=int(avg_assigned),
        composite_score=composite,
        estimated_penalty=estimated_penalty,
        uncovered_tasks=int(avg_uncovered),
    )
