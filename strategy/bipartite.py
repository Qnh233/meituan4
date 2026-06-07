"""二分图匹配策略：手写匈牙利算法。

仅处理单任务候选（task_count == 1），将问题建模为二分图最大权匹配。
纯 Python 标准库实现。
"""

from strategy.base import BaseStrategy, register
from parser import ProblemData


def _hungarian_max(cost_matrix: list[list[float]]) -> tuple[float, list[tuple[int, int]]]:
    """匈牙利算法求二分图最大权匹配（最大化）。

    cost_matrix: m×n 矩阵，m=任务数，n=骑手数。
    返回 (最大总权重, [(task_idx, courier_idx), ...])。
    """
    m = len(cost_matrix)
    if m == 0:
        return 0.0, []
    n = len(cost_matrix[0])
    if n == 0:
        return 0.0, []

    # 转为最小化问题
    max_val = max(max(row) for row in cost_matrix)
    cost = [[max_val - v for v in row] for row in cost_matrix]

    # 方阵化（补充虚拟节点）
    size = max(m, n)
    for i in range(size):
        if i >= len(cost):
            cost.append([0.0] * size)
        else:
            while len(cost[i]) < size:
                cost[i].append(0.0)

    # 标准匈牙利算法
    u = [0.0] * (size + 1)
    v = [0.0] * (size + 1)
    p = [0] * (size + 1)
    way = [0] * (size + 1)

    for i in range(1, size + 1):
        p[0] = i
        j0 = 0
        minv = [float("inf")] * (size + 1)
        used = [False] * (size + 1)
        while True:
            used[j0] = True
            i0 = p[j0]
            delta = float("inf")
            j1 = 0
            for j in range(1, size + 1):
                if not used[j]:
                    cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j] = cur
                        way[j] = j0
                    if minv[j] < delta:
                        delta = minv[j]
                        j1 = j
            for j in range(size + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break

    # 提取匹配
    matches = []
    total = 0.0
    for j in range(1, size + 1):
        if p[j] > 0:
            i = p[j] - 1
            if i < m and j - 1 < n:
                w = cost_matrix[i][j - 1]
                if w > 0:
                    matches.append((i, j - 1))
                    total += w

    return total, matches


@register(name="HungarianPartial")
class HungarianPartial(BaseStrategy):
    """匈牙利算法：仅处理单任务候选，求二分图最大权匹配。

    权重公式：willingness / (total_score + 1) — 平衡接单概率和成本。
    """

    name = "HungarianPartial"
    description = "手写匈牙利算法处理单任务候选，权重=willingness/(score+1)"

    def solve(self, data: ProblemData) -> list[tuple[str, list[str]]]:
        # 仅取单任务候选
        singles = [c for c in data.candidates if c.task_count == 1 and c.willingness > 0]
        if not singles:
            return []

        tasks = sorted(data.all_tasks)
        couriers = sorted(set(c.courier_id for c in singles))
        task_idx = {t: i for i, t in enumerate(tasks)}
        courier_idx = {c: i for i, c in enumerate(couriers)}

        # 构建 cost matrix: 权重 = willingness / (score + 1)
        matrix = [[0.0] * len(couriers) for _ in range(len(tasks))]
        for c in singles:
            ti = task_idx.get(c.task_ids[0])
            ci = courier_idx.get(c.courier_id)
            if ti is not None and ci is not None:
                weight = c.willingness / (c.total_score + 1)
                if weight > matrix[ti][ci]:
                    matrix[ti][ci] = weight

        total_weight, matches = _hungarian_max(matrix)

        # 转为输出格式
        assigned_couriers = set()
        assigned_tasks = set()
        result = []
        for ti, ci in matches:
            task_id = tasks[ti]
            courier_id = couriers[ci]
            if courier_id in assigned_couriers or task_id in assigned_tasks:
                continue
            candidate = data.get_candidate((task_id,), courier_id)
            if candidate:
                assigned_couriers.add(courier_id)
                assigned_tasks.add(task_id)
                result.append((task_id, [courier_id]))

        # 补充：对未覆盖的任务尝试贪心
        uncovered_tasks = data.all_tasks - assigned_tasks
        if uncovered_tasks:
            remaining = [
                c for c in data.candidates
                if c.willingness > 0
                and c.courier_id not in assigned_couriers
                and not any(t in assigned_tasks for t in c.task_ids)
            ]
            remaining.sort(key=lambda c: c.total_score / c.task_count)
            for c in remaining:
                if c.courier_id in assigned_couriers:
                    continue
                if any(t in assigned_tasks for t in c.task_ids):
                    continue
                assigned_couriers.add(c.courier_id)
                assigned_tasks.update(c.task_ids)
                result.append((",".join(c.task_ids), [c.courier_id]))

        return result
