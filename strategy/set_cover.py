"""多轮贪心 + 加权集合打包策略。

MultiRound: 每轮选出全局最优候选，移除冲突行，重复直到无法继续。
IterativeMulti: 多轮变种，每轮用不同排序策略，在不同轮次中平衡覆盖和成本。
"""

from strategy.base import BaseStrategy, register
from parser import ProblemData


def _multi_round_core(data: ProblemData, *,
                      sort_key: str = "ratio",
                      max_rounds: int | None = None) -> list[tuple[str, list[str]]]:
    """多轮贪心核心：每轮从剩余候选中选择最优，移除冲突。"""
    remaining = [c for c in data.candidates if c.willingness > 0]
    assigned_tasks: set[str] = set()
    assigned_couriers: set[str] = set()
    result = []

    rounds = 0
    while remaining and (max_rounds is None or rounds < max_rounds):
        # 过滤已不可用的候选
        valid = [
            c for c in remaining
            if c.courier_id not in assigned_couriers
            and not any(t in assigned_tasks for t in c.task_ids)
        ]
        if not valid:
            break

        # 按策略排序
        if sort_key == "ratio":
            valid.sort(key=lambda c: c.willingness / max(c.total_score, 0.001), reverse=True)
        elif sort_key == "score":
            valid.sort(key=lambda c: c.total_score)
        elif sort_key == "willingness":
            valid.sort(key=lambda c: c.willingness, reverse=True)
        elif sort_key == "unit_score":
            valid.sort(key=lambda c: c.total_score / c.task_count)
        else:
            valid.sort(key=lambda c: c.willingness / max(c.total_score, 0.001), reverse=True)

        # 选最优
        best = valid[0]
        assigned_couriers.add(best.courier_id)
        assigned_tasks.update(best.task_ids)
        result.append((",".join(best.task_ids), [best.courier_id]))

        rounds += 1

    return result


@register(name="MultiRound")
class MultiRound(BaseStrategy):
    """多轮贪心：每轮选出性价比最高的候选，移除冲突后重复。"""
    name = "MultiRound"
    description = "多轮贪心：每轮选willingness/score最高的候选，移除冲突后继续"

    def solve(self, data: ProblemData) -> list[tuple[str, list[str]]]:
        return _multi_round_core(data, sort_key="ratio")


@register(name="IterativeMulti")
class IterativeMulti(BaseStrategy):
    """迭代多策略：先后用不同排序做多轮分配，剩余未覆盖任务用贪心补全。"""

    name = "IterativeMulti"
    description = "迭代多策略：先ratio贪心→补willingness贪心→补unit_score贪心"

    def solve(self, data: ProblemData) -> list[tuple[str, list[str]]]:
        assigned_tasks: set[str] = set()
        assigned_couriers: set[str] = set()
        result = []

        # 阶段1: 性价比优先
        candidates = [c for c in data.candidates if c.willingness > 0]
        candidates.sort(key=lambda c: c.willingness / max(c.total_score, 0.001), reverse=True)
        for c in candidates:
            if c.courier_id in assigned_couriers:
                continue
            if any(t in assigned_tasks for t in c.task_ids):
                continue
            assigned_couriers.add(c.courier_id)
            assigned_tasks.update(c.task_ids)
            result.append((",".join(c.task_ids), [c.courier_id]))

        # 阶段2: 高意愿补全未覆盖任务
        uncovered = data.all_tasks - assigned_tasks
        if uncovered:
            fill = [
                c for c in data.candidates
                if c.willingness > 0.3
                and c.courier_id not in assigned_couriers
                and not any(t in assigned_tasks for t in c.task_ids)
                and any(t in uncovered for t in c.task_ids)
            ]
            fill.sort(key=lambda c: c.willingness, reverse=True)
            for c in fill:
                if c.courier_id in assigned_couriers:
                    continue
                if any(t in assigned_tasks for t in c.task_ids):
                    continue
                assigned_couriers.add(c.courier_id)
                assigned_tasks.update(c.task_ids)
                result.append((",".join(c.task_ids), [c.courier_id]))

        # 阶段3: 低成本补全剩余
        uncovered = data.all_tasks - assigned_tasks
        if uncovered:
            fill = [
                c for c in data.candidates
                if c.willingness > 0
                and c.courier_id not in assigned_couriers
                and not any(t in assigned_tasks for t in c.task_ids)
                and any(t in uncovered for t in c.task_ids)
            ]
            fill.sort(key=lambda c: c.total_score / c.task_count)
            for c in fill:
                if c.courier_id in assigned_couriers:
                    continue
                if any(t in assigned_tasks for t in c.task_ids):
                    continue
                assigned_couriers.add(c.courier_id)
                assigned_tasks.update(c.task_ids)
                result.append((",".join(c.task_ids), [c.courier_id]))

        return result
