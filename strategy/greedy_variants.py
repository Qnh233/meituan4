"""贪心变种策略：5种不同排序/选择策略的贪心分配。

全部 O(n log n)，只依赖标准库。
"""

from strategy.base import BaseStrategy, register
from parser import ProblemData


def _greedy_core(data: ProblemData, candidates: list, *, single_pass: bool = True) -> list[tuple[str, list[str]]]:
    """贪心核心循环：按给定顺序遍历候选，分配未占用的任务/骑手。"""
    assigned_couriers: set[str] = set()
    assigned_tasks: set[str] = set()
    result = []

    for c in candidates:
        if c.courier_id in assigned_couriers:
            continue
        if c.willingness <= 0:
            continue
        if any(t in assigned_tasks for t in c.task_ids):
            continue
        assigned_couriers.add(c.courier_id)
        assigned_tasks.update(c.task_ids)
        result.append((",".join(c.task_ids), [c.courier_id]))

    return result


@register(name="GreedyScore")
class GreedyScore(BaseStrategy):
    """按 total_score 升序贪心（低分优先 = 低成本优先）。"""
    name = "GreedyScore"
    description = "按 total_score 升序贪心分配，优先选择低成本的候选"

    def solve(self, data: ProblemData) -> list[tuple[str, list[str]]]:
        sorted_cands = sorted(data.candidates, key=lambda c: c.total_score)
        return _greedy_core(data, sorted_cands)


@register(name="GreedyWillingness")
class GreedyWillingness(BaseStrategy):
    """按 willingness 降序贪心（高意愿优先）。"""
    name = "GreedyWillingness"
    description = "按 willingness 降序贪心分配，优先选择接单概率高的候选"

    def solve(self, data: ProblemData) -> list[tuple[str, list[str]]]:
        sorted_cands = sorted(data.candidates, key=lambda c: c.willingness, reverse=True)
        return _greedy_core(data, sorted_cands)


@register(name="GreedyRatio")
class GreedyRatio(BaseStrategy):
    """按 willingness/total_score 降序贪心（性价比优先）。"""
    name = "GreedyRatio"
    description = "按 willingness/total_score 降序贪心，平衡成本和接单概率"

    def solve(self, data: ProblemData) -> list[tuple[str, list[str]]]:
        sorted_cands = sorted(
            data.candidates,
            key=lambda c: c.willingness / max(c.total_score, 0.001),
            reverse=True,
        )
        return _greedy_core(data, sorted_cands)


@register(name="GreedyCoverage")
class GreedyCoverage(BaseStrategy):
    """优先单任务候选，再处理合单（覆盖率优先）。"""
    name = "GreedyCoverage"
    description = "优先分配单任务候选（低成本优先），再处理合单候选"

    def solve(self, data: ProblemData) -> list[tuple[str, list[str]]]:
        singles = [c for c in data.candidates if c.task_count == 1 and c.willingness > 0]
        combined = [c for c in data.candidates if c.task_count > 1 and c.willingness > 0]
        singles.sort(key=lambda c: c.total_score)
        combined.sort(key=lambda c: c.total_score / c.task_count)
        return _greedy_core(data, singles + combined)


@register(name="GreedySetPacking")
class GreedySetPacking(BaseStrategy):
    """加权集合打包贪心：按 score/task_count 排序，优先选单位成本低的候选。"""
    name = "GreedySetPacking"
    description = "加权集合打包：按 total_score/task_count 升序贪心"

    def solve(self, data: ProblemData) -> list[tuple[str, list[str]]]:
        sorted_cands = sorted(
            data.candidates,
            key=lambda c: c.total_score / c.task_count if c.task_count > 0 else float("inf"),
        )
        return _greedy_core(data, sorted_cands)
