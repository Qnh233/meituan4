---
id: online_result_iteration
name: 线上结果驱动的 solver 迭代
description: 将 recent online_result 明细、回放脚本和 solver 代码检查转化为下一轮可验证的启发式改动。
scope: project
triggers: online_result, replay, multi-courier, low_willingness, scarce, solver iteration, 线上评测
---

# 适用场景

当 agent 已经有线上评测 JSON、历史 solver 快照或本地分析脚本时使用。目标是复现“读线上明细 -> 写分析脚本 -> 反推评分结构 -> 小步改 solver -> 提交验证”的闭环。

# 关键经验

- 不要只看本地 DetScore。线上明细里的 `p_complete`、`expected_score`、`cost` 能反推真实惩罚项。
- 非 scarce 场景允许同一任务分配多个骑手。给每个单任务追加一个未使用备选骑手，线上能显著降低失败惩罚。
- 低意愿场景的主要瓶颈是联合完成概率，不是覆盖率。优先检查每个任务是否已经有 2 个骑手。
- scarce 场景骑手不足，不能靠备选；应优化合单覆盖。优先尝试成本感知二单覆盖和 pair swap / 2-opt。
- 参数必须通过线上小步验证。scarce 风险系数在本轮经验里 `170-190` 优于 `140` 和 `250`。

# 推荐工具链

1. 先调用 `analyze_online_results`，比较最近多次提交的 case 分数、multi-courier 数和 bundle 数。
2. 调用 `read_file("solver.py")`，确认当前代码是否已经包含对应机制。
3. 写一个 `runs/<id>/tool_scripts/*.py` 回放脚本，输出每个 online_result 的 case 分数变化、multi 数、bundle 数。
4. 执行脚本并把结果写回本轮 prompt。
5. 只提出一个小步 solver 改动，并保留场景分支保护。

# 反模式

- 不要让线上提交文件依赖 agent 包、web 包、openai 或任何第三方库。
- 不要把项目工具当作任意 shell。项目工具只能在项目目录内读写和运行 Python 分析脚本。
- 不要在 scarce 场景强行追加备选骑手；20 个骑手覆盖 40 单时备选会破坏覆盖。
- 不要大范围重写 parser 或返回格式；历史失败多数来自接口和 ID 处理错误。
