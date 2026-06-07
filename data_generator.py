"""合成数据生成器。

生成与真实数据格式一致的 TSV 配送数据，支持参数化控制所有维度，
用于评测策略在不同数据分布下的鲁棒性。

用法:
  python data_generator.py                    # 生成默认配置数据
  python data_generator.py --preset small     # 小规模预设
  python data_generator.py --preset diverse   # 生成多组不同分布数据
"""

import random
import math
import sys
import os


def generate(
    *,
    n_tasks: int = 40,
    n_couriers: int = 80,
    candidates_per_task: int = 800,
    combined_ratio: float = 0.9,
    max_combined: int = 2,
    score_min: float = 10.0,
    score_max: float = 100.0,
    willingness_alpha: float = 1.5,
    willingness_beta: float = 3.5,
    score_will_corr: float = 0.0,
    seed: int = 0,
) -> str:
    """生成 TSV 格式的配送数据。

    参数:
      n_tasks: 订单数量
      n_couriers: 骑手数量
      candidates_per_task: 每个任务平均生成多少条候选
      combined_ratio: 合单候选占比 (0-1)
      max_combined: 合单最大任务数
      score_min/max: total_score 范围
      willingness_alpha/beta: Beta 分布参数 (控制 willingness 形状)
        - alpha=1.5, beta=3.5: 左偏 (类似真实数据, 中位数≈0.25)
        - alpha=1, beta=1: 均匀分布
        - alpha=3, beta=1.5: 右偏 (高意愿多)
      score_will_corr: score 和 willingness 的目标相关系数
        - 0: 无相关 (类似真实数据)
        - 负值: 低分高意愿 (理想场景)
        - 正值: 低分低意愿 (困难场景)
      seed: 随机种子
    """
    rng = random.Random(seed)

    task_ids = [f"T{i:04d}" for i in range(n_tasks)]
    courier_ids = [f"C{i:03d}" for i in range(n_couriers)]

    total_candidates = n_tasks * candidates_per_task
    n_combined = int(total_candidates * combined_ratio)
    n_single = total_candidates - n_combined

    lines = ["task_id_list\tcourier_id\ttotal_score\twillingness"]

    def make_candidate(task_list, cid):
        # 生成 score (均匀分布)
        score = rng.uniform(score_min, score_max)

        # 生成 willingness (Beta 分布)
        w = rng.betavariate(willingness_alpha, willingness_beta)

        # 施加 score-willingness 相关性 (通过重排实现)
        if score_will_corr != 0:
            # 简单方法: 对 willingness 做微调
            target_w = 1.0 - (score - score_min) / (score_max - score_min)
            if score_will_corr > 0:
                w = w + score_will_corr * (target_w - w)
            else:
                w = w - score_will_corr * (w - target_w)
            w = max(0.001, min(0.999, w))

        w = round(w, 4)
        score = round(score, 3)
        task_str = ",".join(task_list)
        return f"{task_str}\t{cid}\t{score}\t{w}"

    # 生成单任务候选
    for _ in range(n_single):
        t = rng.choice(task_ids)
        c = rng.choice(courier_ids)
        lines.append(make_candidate([t], c))

    # 生成合单候选
    for _ in range(n_combined):
        k = rng.randint(2, min(max_combined, n_tasks))
        tasks = rng.sample(task_ids, k)
        c = rng.choice(courier_ids)
        lines.append(make_candidate(tasks, c))

    # 补充: 确保每个任务至少有一些候选
    task_counts = {t: 0 for t in task_ids}
    for line in lines[1:]:
        task_str = line.split("\t")[0]
        for t in task_str.split(","):
            if t in task_counts:
                task_counts[t] += 1

    min_count = min(task_counts.values())
    if min_count < 10:
        for t, cnt in task_counts.items():
            while cnt < 20:
                c = rng.choice(courier_ids)
                lines.append(make_candidate([t], c))
                cnt += 1

    return "\n".join(lines)


def save(data: str, filepath: str):
    os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(data)
    print(f"  已保存: {filepath} ({len(data.splitlines())-1} 行, {len(data.encode('utf-8'))//1024}KB)")


# ---- 预设配置 ----

PRESETS = {
    "real_like": {
        "description": "模拟真实数据分布",
        "params": dict(n_tasks=40, n_couriers=80, candidates_per_task=800,
                       combined_ratio=0.9, max_combined=2,
                       willingness_alpha=1.5, willingness_beta=3.5),
    },
    # ---- 规模变种 (匹配线上 multi-seed 测试) ----
    "tiny": {
        "description": "极小规模 (6任务/10骑手, 匹配 tiny_seed42)",
        "params": dict(n_tasks=6, n_couriers=10, candidates_per_task=100,
                       combined_ratio=0.5, max_combined=2),
    },
    "small": {
        "description": "小规模 (15任务/20骑手, 匹配 small_seed100)",
        "params": dict(n_tasks=15, n_couriers=20, candidates_per_task=200,
                       combined_ratio=0.7, max_combined=2),
    },
    "small_v2": {
        "description": "小规模变种2 (不同seed)",
        "params": dict(n_tasks=15, n_couriers=22, candidates_per_task=250,
                       combined_ratio=0.75, max_combined=2,
                       willingness_alpha=2.0, willingness_beta=4.0),
    },
    "medium": {
        "description": "中规模 (30任务/50骑手, 匹配 medium_seed201/202/203)",
        "params": dict(n_tasks=30, n_couriers=50, candidates_per_task=500,
                       combined_ratio=0.85, max_combined=3),
    },
    "medium_v2": {
        "description": "中规模变种2 (不同seed, 略高意愿)",
        "params": dict(n_tasks=30, n_couriers=55, candidates_per_task=550,
                       combined_ratio=0.88, max_combined=3,
                       willingness_alpha=2.0, willingness_beta=3.0),
    },
    "medium_v3": {
        "description": "中规模变种3 (不同seed, 略低意愿+正相关)",
        "params": dict(n_tasks=30, n_couriers=45, candidates_per_task=480,
                       combined_ratio=0.82, max_combined=3,
                       willingness_alpha=1.2, willingness_beta=4.0,
                       score_will_corr=0.3),
    },
    "large": {
        "description": "大规模 (40任务/80骑手, 匹配 large_seed301)",
        "params": dict(n_tasks=40, n_couriers=80, candidates_per_task=800,
                       combined_ratio=0.9, max_combined=2,
                       willingness_alpha=1.5, willingness_beta=3.5),
    },
    "large_v2": {
        "description": "大规模变种2 (匹配 large_seed302, 略高噪声)",
        "params": dict(n_tasks=40, n_couriers=80, candidates_per_task=850,
                       combined_ratio=0.88, max_combined=2,
                       willingness_alpha=1.7, willingness_beta=3.0,
                       score_min=5.0, score_max=120.0),
    },
    # ---- 特殊分布 ----
    "scarce_couriers": {
        "description": "稀缺骑手: 20骑手/40任务 (匹配 scarce_couriers_seed401)",
        "params": dict(n_tasks=40, n_couriers=20, candidates_per_task=300,
                       combined_ratio=0.85, max_combined=3,
                       willingness_alpha=1.5, willingness_beta=3.5,
                       score_will_corr=0.2),
    },
    "scarce_v2": {
        "description": "稀缺骑手变种2: 极度稀缺 15骑手/40任务",
        "params": dict(n_tasks=40, n_couriers=15, candidates_per_task=250,
                       combined_ratio=0.9, max_combined=4,
                       willingness_alpha=1.8, willingness_beta=2.5,
                       score_will_corr=0.1),
    },
    "scarce_v3": {
        "description": "稀缺骑手变种3: 中等稀缺 30骑手/50任务",
        "params": dict(n_tasks=50, n_couriers=30, candidates_per_task=400,
                       combined_ratio=0.88, max_combined=3,
                       willingness_alpha=1.3, willingness_beta=4.0),
    },
    "high_noise": {
        "description": "高噪声场景: 分数方差大+willingness波动 (匹配 high_noise_seed601)",
        "params": dict(n_tasks=30, n_couriers=60, candidates_per_task=900,
                       combined_ratio=0.85, max_combined=2,
                       willingness_alpha=1.2, willingness_beta=2.5,
                       score_min=1.0, score_max=200.0, score_will_corr=0.0),
    },
    "high_willingness": {
        "description": "高意愿场景 (右偏Beta, 中位数≈0.65)",
        "params": dict(n_tasks=40, n_couriers=80, candidates_per_task=800,
                       willingness_alpha=3.0, willingness_beta=1.5),
    },
    "low_willingness": {
        "description": "低意愿场景 (极端左偏Beta, 中位数≈0.1, 匹配 low_willingness_seed501)",
        "params": dict(n_tasks=30, n_couriers=60, candidates_per_task=800,
                       willingness_alpha=0.8, willingness_beta=5.0,
                       score_will_corr=0.3),
    },
    "low_willingness_v2": {
        "description": "低意愿变种2: 中等偏低但更均匀",
        "params": dict(n_tasks=30, n_couriers=60, candidates_per_task=800,
                       willingness_alpha=1.0, willingness_beta=3.0,
                       score_will_corr=0.0),
    },
    "ideal_correlation": {
        "description": "理想场景: 低分高意愿 (score-will 负相关 -0.5)",
        "params": dict(n_tasks=40, n_couriers=80, candidates_per_task=800,
                       score_will_corr=-0.5),
    },
    "hard_correlation": {
        "description": "困难场景: 低分低意愿 (score-will 正相关 +0.5)",
        "params": dict(n_tasks=40, n_couriers=80, candidates_per_task=800,
                       score_will_corr=0.5),
    },
    "sparse": {
        "description": "稀疏场景 (每任务仅50候选)",
        "params": dict(n_tasks=40, n_couriers=80, candidates_per_task=50,
                       combined_ratio=0.5, max_combined=2),
    },
    "dense": {
        "description": "密集场景 (每任务2000候选)",
        "params": dict(n_tasks=40, n_couriers=80, candidates_per_task=2000,
                       combined_ratio=0.95, max_combined=2),
    },
    "multi_courier": {
        "description": "多骑手场景: 骑手远多于任务",
        "params": dict(n_tasks=30, n_couriers=200, candidates_per_task=600,
                       combined_ratio=0.8, max_combined=2),
    },
}


# 校准预设 — 参数经过本地DetScore vs V6线上惩罚匹配 (2026-05-15)
# 关键：线上"完成率"=确定性覆盖(DetCov)，非MC模拟
# 使用方法: generate(**CALIBRATED_PRESETS["large"]) 等
CALIBRATED_PRESETS = {
    "calibrated_tiny": {
        "description": "校准: 极小规模 (DetScore≈210, matching tiny_seed42)",
        "params": dict(n_tasks=6, n_couriers=10, candidates_per_task=100,
                       combined_ratio=0.5, max_combined=2,
                       willingness_alpha=1.8, willingness_beta=3.5,
                       score_min=10.0, score_max=80.0, score_will_corr=0.0),
    },
    "calibrated_small": {
        "description": "校准: 小规模 (DetScore≈444, matching small_seed100)",
        "params": dict(n_tasks=15, n_couriers=20, candidates_per_task=200,
                       combined_ratio=0.7, max_combined=2,
                       willingness_alpha=1.3, willingness_beta=4.0,
                       score_min=15.0, score_max=100.0, score_will_corr=0.0),
    },
    "calibrated_medium": {
        "description": "校准: 中规模 (DetScore≈843, matching medium_seed203)",
        "params": dict(n_tasks=30, n_couriers=50, candidates_per_task=500,
                       combined_ratio=0.85, max_combined=3,
                       willingness_alpha=1.3, willingness_beta=4.0,
                       score_min=15.0, score_max=100.0, score_will_corr=0.0),
    },
    "calibrated_large": {
        "description": "校准: 大规模 (DetScore≈1071, matching large_seed301)",
        "params": dict(n_tasks=40, n_couriers=80, candidates_per_task=800,
                       combined_ratio=0.9, max_combined=2,
                       willingness_alpha=1.5, willingness_beta=3.0,
                       score_min=20.0, score_max=120.0, score_will_corr=0.0),
    },
    "calibrated_scarce": {
        "description": "校准: 稀缺骑手 (DetScore≈1713, matching scarce_couriers_seed401)",
        "params": dict(n_tasks=40, n_couriers=20, candidates_per_task=300,
                       combined_ratio=0.85, max_combined=3,
                       willingness_alpha=2.0, willingness_beta=2.5,
                       score_min=50.0, score_max=200.0, score_will_corr=0.2),
    },
    "calibrated_low_will": {
        "description": "校准: 低意愿 (DetScore≈1774, matching low_willingness_seed501) 注意-524 gap但DetCov已1.0",
        "params": dict(n_tasks=30, n_couriers=60, candidates_per_task=800,
                       combined_ratio=0.9, max_combined=2,
                       willingness_alpha=1.5, willingness_beta=3.0,
                       score_min=50.0, score_max=200.0, score_will_corr=0.3),
    },
    "calibrated_high_noise": {
        "description": "校准: 高噪声 (DetScore≈894, matching high_noise_seed601)",
        "params": dict(n_tasks=30, n_couriers=60, candidates_per_task=900,
                       combined_ratio=0.85, max_combined=2,
                       willingness_alpha=2.0, willingness_beta=3.0,
                       score_min=20.0, score_max=120.0, score_will_corr=0.0),
    },
}


def generate_all_presets(output_dir: str = "data/synthetic"):
    """生成所有预设场景数据。"""
    os.makedirs(output_dir, exist_ok=True)
    for name, preset in PRESETS.items():
        params = preset["params"].copy()
        desc = preset["description"]
        params["seed"] = hash(name) % 10000
        print(f"[{name}] {desc}")
        data = generate(**params)
        save(data, f"{output_dir}/{name}.txt")
    print(f"\n共生成 {len(PRESETS)} 组合成数据到 {output_dir}/")


if __name__ == "__main__":
    preset_name = "real_like"
    output = "data/synthetic/test_data.txt"

    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == "--preset" and i + 1 < len(args):
            preset_name = args[i + 1]
        elif a == "--output" and i + 1 < len(args):
            output = args[i + 1]

    if preset_name == "diverse":
        generate_all_presets()
    elif preset_name in PRESETS:
        preset = PRESETS[preset_name]
        print(f"[{preset_name}] {preset['description']}")
        data = generate(**preset["params"])
        save(data, output)
    else:
        print(f"未知预设: {preset_name}")
        print(f"可用预设: {list(PRESETS.keys())} + diverse")
