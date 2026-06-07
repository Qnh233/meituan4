"""批量策略评估脚本。

运行所有已注册策略，在 large_seed301.txt 上评测，生成排行榜。
"""

import time
import sys

from parser import parse
from judge import evaluate_deterministic, evaluate_monte_carlo
from strategy import list_strategies, get_strategy
from library.store import update_performance


def evaluate_all(data_file: str = "large_seed301.txt", mc_sims: int = 100):
    with open(data_file, encoding="utf-8") as f:
        raw = f.read()

    data = parse(raw)
    print(f"数据: {len(data.candidates)} 候选, {len(data.all_tasks)} 任务, {len(data.all_couriers)} 骑手")

    strategies = list_strategies()
    print(f"策略数: {len(strategies)}\n")

    results = []

    for name in strategies:
        cls = get_strategy(name)
        instance = cls()

        # 计时
        t0 = time.perf_counter()
        try:
            plan = instance.solve(data)
        except Exception as e:
            print(f"[ERROR] {name}: {e}")
            continue
        elapsed = time.perf_counter() - t0

        # 确定性评测
        det = evaluate_deterministic(plan, data)
        # 蒙特卡洛评测
        mc = evaluate_monte_carlo(plan, data, n_simulations=mc_sims)

        results.append({
            "name": name,
            "description": instance.description,
            "elapsed": elapsed,
            "det_cov": det.coverage_rate,
            "det_score": det.total_score,
            "mc_cov": mc.coverage_rate,
            "mc_score": mc.total_score,
            "assignments": len(plan),
        })

        # 更新策略库
        update_performance(
            sid=name, det_cov=det.coverage_rate, det_score=det.total_score,
            mc_cov=mc.coverage_rate, mc_score=mc.total_score, n_sims=mc_sims,
        )

    # 按 MC 覆盖率排序
    results.sort(key=lambda r: r["mc_cov"], reverse=True)

    # 打印排行榜
    header = f"{'Rank':<5} {'策略':<25} {'耗时':<8} {'Det Cov':<9} {'Det Score':<10} {'MC Cov':<9} {'MC Score':<10} {'Assign':<7}"
    print(header)
    print("-" * len(header))

    for i, r in enumerate(results, 1):
        print(f"{i:<5} {r['name']:<25} {r['elapsed']:.3f}s  "
              f"{r['det_cov']:.4f}    {r['det_score']:.1f}      "
              f"{r['mc_cov']:.4f}    {r['mc_score']:.1f}      "
              f"{r['assignments']}")

    print(f"\nTop 3 by MC 覆盖率:")
    for i, r in enumerate(results[:3], 1):
        print(f"  {i}. {r['name']} — MC覆盖率={r['mc_cov']:.4f}, MC分数={r['mc_score']:.1f}, "
              f"耗时={r['elapsed']:.3f}s, 描述: {r['description']}")

    return results


if __name__ == "__main__":
    mc_n = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    evaluate_all(mc_sims=mc_n)
