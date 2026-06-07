"""跨数据集策略评测 — 验证策略在不同数据分布下的泛化能力。"""

import sys
import time
from pathlib import Path

from parser import parse
from judge import evaluate_monte_carlo
from strategy import list_strategies, get_strategy


def evaluate_on_datasets(data_dir: str = "data/synthetic", mc_sims: int = 50):
    data_files = sorted(Path(data_dir).glob("*.txt"))
    if not data_files:
        print(f"无数据文件: {data_dir}")
        return

    strategies = [s for s in list_strategies() if s not in ("SimulatedAnnealing", "TabuSearch")]
    print(f"策略数: {len(strategies)}, 数据集数: {len(data_files)}\n")

    # 排名追踪: strategy -> 在每个数据集上的 rank
    rank_history: dict[str, list[int]] = {s: [] for s in strategies}

    for data_file in data_files:
        raw = data_file.read_text(encoding="utf-8")
        data = parse(raw)

        results = []
        for name in strategies:
            cls = get_strategy(name)
            instance = cls()
            t0 = time.perf_counter()
            plan = instance.solve(data)
            elapsed = time.perf_counter() - t0
            mc = evaluate_monte_carlo(plan, data, n_simulations=mc_sims)
            results.append((name, mc.coverage_rate, mc.total_score, elapsed, len(plan)))

        results.sort(key=lambda r: r[1], reverse=True)
        for rank, (name, cov, score, elapsed, n_assign) in enumerate(results, 1):
            rank_history[name].append(rank)

        best = results[0]
        print(f"{data_file.stem:25s} | top: {best[0]:25s} cov={best[1]:.3f} | "
              f"tasks={len(data.all_tasks)} couriers={len(data.all_couriers)} "
              f"cands={len(data.candidates)}")

    # 汇总排名
    print(f"\n{'='*80}")
    print(f"{'策略':<25s} {'平均排名':>8s} {'Top1次数':>8s} {'Top3次数':>8s} {'最低排名':>8s}")
    print("-" * 60)

    summary = []
    for name in strategies:
        ranks = rank_history[name]
        avg_rank = sum(ranks) / len(ranks)
        top1 = sum(1 for r in ranks if r == 1)
        top3 = sum(1 for r in ranks if r <= 3)
        worst = max(ranks)
        summary.append((name, avg_rank, top1, top3, worst))

    summary.sort(key=lambda x: x[1])
    for name, avg_rank, top1, top3, worst in summary:
        print(f"{name:<25s} {avg_rank:>8.2f} {top1:>8} {top3:>8} {worst:>8}")

    return summary


if __name__ == "__main__":
    data_dir = sys.argv[1] if len(sys.argv) > 1 else "data/synthetic"
    mc_n = int(sys.argv[2]) if len(sys.argv) > 2 else 50
    evaluate_on_datasets(data_dir, mc_sims=mc_n)
