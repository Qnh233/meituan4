---
id: research_breakthrough
name: 外部研究转策略
description: 把论文或网页研究结果转成纯 Python 启发式，而不是照搬复杂求解器。
scope: generic
triggers: research, arxiv, paper, 文献, 突破, set packing, heuristic
---

# 适用场景

连续多轮没有采纳，或者当前策略陷入 V9 局部最优时使用。

# 研究转化规则

- 如果论文涉及 ILP、SAT、MIP、OR-Tools，只提取启发式思想，不调用外部库。
- 如果论文涉及 local search，转化为 bounded repair / destroy-rebuild / accepted-only replacement。
- 如果论文涉及 beam search，只在小任务或稀缺场景做窄束宽搜索，其他场景保持 best。
- 如果论文涉及 set packing，重点关注超边冲突、候选剪枝、覆盖修复。

# 输出要求

- 先说明采用了哪条研究线索。
- 只做一个明确改动，不要同时引入多种复杂机制。
