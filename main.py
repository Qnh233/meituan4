"""AutoResearch Agent 主入口。

solve(input_text) -> list 是对外唯一接口。
在线推理路径：解析 → 特征提取 → 策略选择 → 求解 → 返回最优结果。
"""

from parser import parse
from strategy import list_strategies, get_strategy


# 按 MC 覆盖率排序的推荐策略（Phase 2 排行榜证实）
DEFAULT_STRATEGIES = [
    "GreedyWillingness",   # MC 93.6% — 高覆盖率
    "HungarianPartial",    # MC 82.4% — 平衡成本
    "GreedyRatio",         # MC 80.1% — 性价比
]


def solve(input_text: str) -> list:
    data = parse(input_text)
    if not data.candidates:
        return []

    # Phase 2: 使用注册的策略按优先级求解
    # 后续 Phase 4 会替换为策略库查询 + 时间预算分配
    for strategy_name in DEFAULT_STRATEGIES:
        try:
            cls = get_strategy(strategy_name)
            instance = cls()
            result = instance.solve(data)
            if result:
                return result
        except Exception:
            continue

    return []


# ---- 本地测试 ----
if __name__ == "__main__":
    import time

    with open("large_seed301.txt", encoding="utf-8") as f:
        raw = f.read()

    # Step 1: solve
    t0 = time.perf_counter()
    plan = solve(raw)
    elapsed = time.perf_counter() - t0

    # Step 2: parse for judge
    data = parse(raw)
    print(f"解析完成: {len(data.candidates)} 候选行, {len(data.all_tasks)} 订单, {len(data.all_couriers)} 骑手")
    print(f"分配结果: {len(plan)} 条分配, 耗时 {elapsed:.3f}s")

    # Step 3: deterministic judge
    det = evaluate_deterministic(plan, data)
    print(f"\n--- 确定性评测 ---")
    print(f"  覆盖率: {det.coverage_rate:.4f} ({det.covered_tasks}/{det.total_tasks})")
    print(f"  总分: {det.total_score:.2f}")
    print(f"  综合得分: {det.composite_score:.4f}")

    # Step 4: Monte Carlo judge
    print(f"\n--- 蒙特卡洛评测 (N=100) ---")
    mc = evaluate_monte_carlo(plan, data, n_simulations=100)
    print(f"  平均覆盖率: {mc.coverage_rate:.4f} ({mc.covered_tasks}/{mc.total_tasks})")
    print(f"  平均总分: {mc.total_score:.2f}")
    print(f"  平均接单数: {mc.assigned_count:.1f}")
    print(f"  综合得分: {mc.composite_score:.4f}")
