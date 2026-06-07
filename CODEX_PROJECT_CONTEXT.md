# Codex 项目理解与判断笔记

> 用途：这是给后续 Codex/Agent 快速接手本仓库时使用的辅助判断文件。它不替代 `AGENTS.md`、`CLAUDE.md` 或赛题原文，而是把“读完项目后应如何判断下一步”的要点压缩在一起。

## 1. 项目一句话定位

这是一个美团 Keeta 外卖配送订单-骑手匹配优化赛题仓库。问题本质是带合单候选的组合优化：每条候选记录表示“一个骑手可以接一组订单”，目标是在订单、骑手不重复使用的约束下覆盖尽可能多订单，并尽量降低 `total_score`。

更关键的是，赛题目标不是只手写一个求解器，而是构建一个离线 AutoResearch / AutoSolver Agent：让 LLM 自主提出策略、生成代码、评估结果、沉淀经验，再把表现最好的策略内联进线上提交用的 `solver.py`。

## 2. 必须优先遵守的边界

- 线上只提交 `solver.py`，必须包含 `solve(input_text: str) -> list`。
- `solver.py` 必须零第三方依赖，只能用 Python 标准库，贪心类策略最好不写任何 import。
- 在线路径不能调用 LLM，所有 LLM 探索只能发生在离线 Agent 中。
- 线上时限按文档写为 10 秒/测试用例，题面解析中也提到 2-5 秒，因此策略应优先保持简单、稳定、可预测。
- 不能把 `strategy/`、`parser.py`、`judge.py` 等内部模块导入线上 `solver.py`，最终逻辑必须内联。
- 修改求解策略前，应先确认 `DetCov=1.0`，再比较 `DetScore`；不要被本地 MC 覆盖率误导。

## 3. 数据与返回格式

输入是 TSV 文本，字段通常为：

- `task_id_list`：订单 ID 列表，逗号分隔，支持合单。
- `courier_id`：骑手 ID。
- `total_score`：成本或惩罚，越低越好。
- `willingness`：骑手接单概率或意愿。

返回格式必须是：

```python
[(task_id_list_str, [courier_id, ...]), ...]
```

当前主流策略实际返回每个分配只放一个骑手，例如 `("T0001,T0002", ["C003"])`。稀缺场景可能追加少量备份骑手对应的额外分配项，但要非常谨慎，因为线上确认过备份会增加 `total_score` 成本。

## 4. 仓库结构速览

- `solver.py`：当前线上提交候选，必须保持单文件、零第三方依赖。
- `solver_v*.py`：后续实验版本，不等于当前提交物；需要结合线上评测 JSON 判断是否真的更优。
- `snapshots/`：历史导出的 solver 快照和元数据。
- `VERSION_HISTORY.md`：V1-V16 的策略演进、线上结果、经验教训。
- `AGENTS.md` / `CLAUDE.md`：项目规则、赛题概述、离线/在线边界。`CLAUDE.md` 内容更完整，包含 V7 后修正的评测协议。
- `赛题描述.txt`：赛题背景和官方任务定位。
- `parser.py`：本地结构化解析器。
- `judge.py`：本地确定性评测和蒙特卡洛评测。
- `evaluate.py`、`eval_quick.py`、`cross_eval.py`、`eval_versions_calibrated.py`：本地批量评估工具。
- `data_generator.py`、`calibrate_data.py`、`data/synthetic/`：合成数据与校准数据。
- `strategy/`：手工策略模块和注册表，用于离线/本地评估，不可直接导入线上 `solver.py`。
- `library/`：策略库、生成代码、策略表现记录。
- `agent/`：离线 LLM 搜索 Agent。当前入口是 `agent/simple_loop.py`，旧图编排文件已清理。
- `experience/principles.json`：沉淀的设计模式、失败模式和关键洞察。
- `evaluations/online_result_*.json`：线上提交结果，判断真实优劣时优先级最高。
- `papers/`：Agent 自动发现算法相关论文资料。

## 5. 当前提交物理解

当前根目录 `solver.py` 是 `V9_TaskCountRoute`，核心是四路分支：

1. `courier_task_ratio < 0.8`：稀缺场景，走集合覆盖 + 最多 3 个边际增益备份。
2. `mean_willingness < 0.25`：低意愿场景，走意愿分桶 + 桶内 `willingness/score` 性价比排序。
3. `n_tasks <= 15 or n_tasks >= 40`：小任务或大任务场景，走意愿分桶 + 桶内成本排序。
4. 其他中等任务数场景：走 `willingness/score` 贪心排序。

这个版本的依据来自线上结果：任务数与最佳排序策略呈 U 型关系，小/大任务池用 Bucketed 更好，中等任务池用 GreedyRatio 更好。`VERSION_HISTORY.md` 记录 V9 线上平均分约 `1012.22`，10/10 完成，是早期历史最佳。`evaluations/` 中多次线上结果也显示 `1012.2199` 是当前已记录的最佳平均分之一。

## 6. 评测协议和关键教训

V7 失败后，项目里形成了更可靠的判断协议：

- 主指标：确定性覆盖率 `DetCov` 必须等于 1.0。
- 优化目标：在 `DetCov=1.0` 前提下最小化 `DetScore`。
- MC 覆盖率只作为鲁棒性参考，不能作为线上优劣的主要依据。
- 线上结果比合成数据和本地 MC 更可靠。
- 备份策略只有在确定覆盖不足时才有价值；覆盖已满时，备份几乎只会增加成本。

这一点是后续改策略时最重要的判断准则：不要为了提升本地 MC 指标牺牲线上确定性成本。

## 7. 已验证有效的策略模式

- 意愿分桶 + 桶内成本排序：在正常场景中能兼顾覆盖和成本。
- `willingness/score` 排序：在中等任务数场景表现好。
- 数据特征驱动分流：比单一排序键更鲁棒。
- 稀缺场景集合覆盖：能把极度稀缺场景从覆盖不足拉到 100% 覆盖。
- 低意愿场景桶内性价比排序：比纯桶内成本更稳。

## 8. 已验证失败或风险较高的方向

- 纯成本优先：会过早消耗关键骑手，破坏后续覆盖。
- 大量备份：在线上覆盖已满时只增加成本。
- 单一统一排序键：无法覆盖不同数据分布。
- 匈牙利只做单任务匹配再补合单：会破坏合单协同。
- 本地 MC 改善直接当作线上改善：V7 已证明风险很高。
- 在 `solver.py` 中引入离线依赖或内部模块导入：违反提交规范。

## 9. 离线 Agent 工作流

离线搜索入口是：

```bash
python search.py
```

实际参数由 `agent/simple_loop.py` 提供，当前推荐流程是单一顺序 loop：

1. 检查预算。
2. LLM 选择探索方向并生成策略代码。
3. 语法、接口、运行、格式验证。
4. 在校准数据上做 `DetCov` / `DetScore` 评测。
5. 全覆盖且平均 `DetScore` 改善才采纳。
6. 采纳后写入 `library/`、`runs/` 和 `snapshots/`。
7. 默认不覆盖 `solver.py`；只有显式传 `--export-best` 才导出为提交物。

离线依赖在 `requirements-agent.txt`，当前只需要 `openai`。密钥配置应使用 `agent/agent_llm.settings.json` 或环境变量，不应提交密钥。

## 10. 接手时建议的阅读顺序

1. 先读 `CODEX_PROJECT_CONTEXT.md`，建立当前判断框架。
2. 再读 `CLAUDE.md`，确认最新评测协议和项目边界。
3. 读 `solver.py`，确认当前线上提交物是什么。
4. 读 `VERSION_HISTORY.md`，理解 V1-V16 为什么演进到 V9。
5. 汇总 `evaluations/online_result_*.json`，确认后续实验是否真的超过 V9。
6. 若要动离线 Agent，先读 `SIMPLE_AGENT_LOOP.md` 和 `agent/simple_loop.py`。
7. 若要动本地评测，再读 `judge.py`、`eval_quick.py`、`data_generator.py`。

## 11. 后续改动前的检查清单

- 新策略是否仍然只需要标准库？
- 是否保证 `solve(input_text: str) -> list` 返回格式正确？
- 是否处理了无 header 输入？
- 是否跳过了 `willingness <= 0` 的候选？
- 是否避免重复使用同一订单或同一骑手？
- 是否优先检查 `DetCov=1.0`？
- 是否用线上 JSON 或校准评测验证，而不是只看 MC？
- 如果导出为 `solver.py`，是否立即运行本地验证，确认无 ImportError？

## 12. 当前可疑点

- `main.py` 的本地测试段调用 `evaluate_deterministic` 和 `evaluate_monte_carlo`，但文件顶部没有导入它们；如果直接运行 `python main.py` 可能会报 `NameError`。
- `solver_v42_adaptive.py` 和 `solver_v43_retune.py` 等后续版本采用“多策略生成后选 DetScore 最低”的思路，但不能只凭本地构造判断，需要对照线上结果。
- `CLAUDE.md` 中仍写过“V6 当前最优”的历史结论，但 `VERSION_HISTORY.md` 和线上 JSON 显示 V9 平均分更低；后续判断应以 `VERSION_HISTORY.md` 后段和 `evaluations/` 汇总为准。
- `AGENTS.md` 与 `CLAUDE.md` 内容有重叠，若两者不一致，优先采用更接近最新评测协议和线上结果的描述。

## 13. 我的默认判断原则

后续如果没有用户特别指定，我会按以下原则处理这个仓库：

- 先保护 `solver.py` 的零依赖提交约束。
- 策略改动先追求 `DetCov=1.0`，再追求 `DetScore` 降低。
- 不轻易引入复杂算法，除非能在 10 秒内稳定完成且有明确评测收益。
- 优先复用已有评测脚本、策略库和离线 Agent，不重新造评测框架。
- 对“本地看起来更好”的结果保持怀疑，最终以线上结果或校准协议为准。
- 修改后必须说明改动原因、验证方式和是否存在未验证风险。
