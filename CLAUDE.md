# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 赛道概述

美团 Keeta 外卖配送订单-骑手匹配优化问题（NP-hard 组合优化）。本题目标不是手写求解器，而是构建一个 **AutoResearch Agent**：让 LLM 自主提出策略、生成代码、评估效果、迭代改进，在无人干预下持续逼近最优解。

## 数据格式

输入为 TSV 文本，字段：`task_id_list`（订单ID，逗号分隔支持合单）、`courier_id`（骑手ID）、`total_score`（成本，越低越好）、`willingness`（骑手接单概率）。

约束：每个订单和骑手最多分配一次；同一订单可指派给多位骑手，最先接起者获得。

目标：最大化接单数量 + 最小化 total_score 总和。

## 接口规范

选手必须实现 `solve(input_text: str) -> list` 函数，返回 `[(task_id_list_str, [courier_id, ...]), ...]`。

本地评测：`python3 judge_server.py --test example_solver.py --case small_seed100.txt`（judge_server.py 官方尚未发放，需自建评测沙箱）。

## 线上提交规范

线上只提交一个 `solver.py`，必须包含 `solve(input_text: str) -> list` 函数且**零外部依赖**（纯 Python 标准库 + builtins，无 import 或仅 import 标准库模块）。策略库中的所有策略最终通过此文件交付。

生成 solver.py 时：
1. 将所有逻辑内联到单文件（不要 from strategy/parser/judge 等内部模块导入）
2. 贪心类策略可以不写任何 import（仅用 builtins：set/list/tuple/sorted/float/str）
3. 需要随机数的策略只 import random（标准库）
4. 算法较复杂时用 `# --- 策略名 ---` 分隔注释标注各段逻辑
5. 生成后立即用 `python solver.py` 或本地数据验证无 ImportError

## 离线 Agent 依赖（与线上求解器分离）

- 运行离线 Agent/搜索：**`pip install -r requirements-agent.txt`**（当前仅需 `openai`）。当前架构是 `agent/simple_loop.py` 中的简单顺序 loop，不再使用 LangGraph。
- **LLM 与探索超参**：复制 [`agent/agent_llm.settings.example.json`](agent/agent_llm.settings.example.json) 为 **`agent/agent_llm.settings.json`**（勿提交密钥）；也可用环境变量 `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` / `LLM_TIMEOUT_SECONDS` 覆盖。
- **探索方向是否“被规则框死”**：配置项 **`exploration.direction_mode`**：`heuristic`（默认，将 `extract_direction` 的题干写入 prompt）或 **`open`**（不注入固定方向段，仅靠经验与设计模式段落 + Top-K，由模型自拟）。
- **`solver.py` 提交物仍必须零第三方依赖**：勿在可提交求解器中 `import openai` 等离线依赖。

## 核心架构约束

- **在线时限**：10秒/测试用例 → LLM 调用不能出现在在线路径上
- **离线-在线分离**：离线阶段（数小时）由 LLM 生成策略代码，经本地评测筛选后入策略库；在线阶段从策略库选 Top-K 策略并行执行，返回最优结果
- **评分函数**：线上"completion_rate"=确定性覆盖(所有订单均被分配=100%)，penalty=已分配候选total_score之和（V7失败确认）。MC模拟仅作为本地鲁棒性参考。

## 关键设计决策

- **FunSearch 范式**：LLM 在程序空间（策略代码）上搜索，而非参数空间搜索
- **策略库**：存储 `(code, metadata, performance_vector, embedding)` 四元组，支持相似度检索和多样性采样
- **经验内化**：从成功策略中提取设计模式写回 prompt，指导后续 LLM 生成（而非仅保留代码）
- **模板化策略**：初期让 LLM 调参/组合算子而非从零写代码，降低语法错误率
- **Agent 只能动求解器，不能动评分函数**：评分函数是环境，但 Agent 可学习其近似模型以加速搜索
- **纯 Python 标准库约束**：线上环境无 OR-Tools/networkx/scipy 等第三方库。所有策略代码必须是纯 Python（仅标准库），LLM 生成的是自包含的决策代码，不是对现成求解器的 wrapper。这意味着：无 ILP 求解器、无 min-cost-flow 库调用、无 numpy 加速。Agent 的价值恰恰在于——在没有现成求解器的情况下，自主发现有效的启发式算法

## 合成数据生成

`data_generator.py` 支持 11 种预设场景。**重要：2026-05-15已增加校准预设 `CALIBRATED_PRESETS`，参数经过V6线上DetScore匹配。** 使用校准数据：`generate(**CALIBRATED_PRESETS["calibrated_large"])`。

原始预设仍然可用于极端场景测试。

## 评测协议（V7失败后修正 — 2026-05-15）

**关键发现：线上"completion_rate"=确定性覆盖(DetCov)，非MC模拟。**

证据：V6线上10/10均100%完成率，但本地MC覆盖率在各数据集仅57-89%。V7本地MC改善(+17pp)但线上惩罚反升(+70)，因DetCov已是1.0，备份只增DetScore无益。

**修正后的评测协议：**

1. **主指标（必须）**：确定性覆盖率 DetCov 必须 = 1.0（硬约束）
2. **优化目标**：最小化 DetScore（全部已分配候选的 total_score 之和）
3. **辅助指标**：MC覆盖率作为鲁棒性参考（但不作为主要决策依据）
4. **判定标准**：新策略 DetCov=1.0 且 DetScore < V6 DetScore → 可能是改进；DetCov<1.0 → 无效

**V7灾难可在新协议下避免**：V7 DetScore 501→615 (+23%)，DetCov已1.0，应直接拒绝。

**校准数据生成**：`python calibrate_data.py`（基于V6线上结果校准，产出 `evaluations/calibrated_params.json`）。

## 交叉评测结论 (22 datasets, 8 strategies, est_penalty 排名)

评测指标：`estimated_penalty = MC_score + 100 × uncovered_tasks`（模拟线上惩罚）

| 策略 | 平均排名 | Top1 | Top3 | 结论 |
|------|:---:|:---:|:---:|------|
| **GreedyRatio** | **1.36** | **14/22** | **22/22** | **新默认，扩展数据后反超** |
| IterativeMulti | 2.36 | 0 | 22/22 | 稳定第二，与Ratio同类 |
| GreedyWillingness | 3.45 | 7/22 | 7/22 | 仅在稀缺/高意愿场景最优 |
| GreedySetPacking | 5.68 | 0 | 0 | 覆盖率过低 |
| HungarianPartial | 5.91 | 1/22 | 1/22 | 不鲁棒 |
| GreedyScore | 6.14 | 0 | 0 | 纯成本策略MC覆盖率崩塌 |
| GreedyCoverage | 7.73 | 0 | 0 | 分离单/合单策略无效 |

**solver.py 策略 (V6, 当前最优)**：数据特征驱动三路分支 — c/t<0.8→集合覆盖+≤3备份；mean_w<0.25→Bucket+桶内性价比排序；默认→Bucket+桶内成本排序。线上 avg 1,031.10, 10/10完成。

**线上迭代记录详见 `VERSION_HISTORY.md`**（V1→V7完整记录，含决策复盘、数据、经验教训）。V6为当前最优，V7已回滚。

## 论文库 (`papers/`)

10篇论文覆盖 LLM 自动发现算法的完整技术栈：

### 核心方法论
- **LLM4AlgorithmDesign (Survey)** — LLM 算法设计的系统综述。定义四种范式：**LLM as Optimizer**（方案级搜索）、**LLM as Predictor**（代理评估）、**LLM as Extractor**（特征/知识提取）、**LLM as Designer**（代码级生成）。FunSearch 和 EoH 属于 Designer 范式。我们的 AutoResearch Agent 需要结合全部四种角色。
- **AgenticRL (Survey)** — Agent RL 综述。将 LLM Agent 形式化为 POMDP，强调 RL 是让 planning/tool use/memory/reasoning/self-improvement 从静态模块变为自适应行为的关键机制。

### 自进化 Agent
- **GodelAgent** — 自指涉 Agent 框架。Agent 能读写自身代码（monkey patching），递归自改进。关键思想：消除人类设计先验，让 Agent 搜索完整的设计空间。可借鉴其"自我感知→自我修改→递归优化"循环。
- **EvolveR** — 经验驱动的自进化生命周期。两阶段：(1) Offline Self-Distillation 把交互轨迹提炼为可复用的策略原则；(2) Online Interaction 检索原则指导决策。直接适用于我们的策略经验内化。
- **FunBO** — LLM 驱动的贝叶斯优化（PDF 损坏，可参考其思想：用 LLM 作为 BO 的 acquisition function）。

### 多 Agent 协作与精炼
- **MAgICoRe** — 多 Agent 粗到细迭代精炼。核心机制：(1) 难度感知分类（easy=粗粒度聚合，hard=细粒度精炼）、(2) PRM 定位错误步骤、(3) 多 Agent 迭代评审。对我们的启示：不同难度测试用例用不同策略。
- **WALLE** — 世界模型对齐。用 neurosymbolic 方法从交互轨迹中学习规则（code），以弥合 LLM 先验与环境动态之间的 gap。可借鉴其"对比预测 vs 真实轨迹→学习规则"的模式。

### 注意
- `FunSearch_Nature2024.pdf` 文件名有误，实际内容是 PM10 空气污染论文（arXiv:2311.12054 physics.ao-ph），非 DeepMind FunSearch。如需原始 FunSearch 论文，参考 arXiv:2311.12054→正确 ID 为 arXiv:2311.12054→应为 Nature 2024 "Mathematical discoveries from program search with large language models" (Romera-Paredes et al.)。

### 对本赛道的战略启示

1. **架构必定是多范式混合**：LLM as Designer（生成求解策略代码）+ LLM as Optimizer（在策略空间搜索）+ LLM as Extractor（从成功策略提取设计模式）+ LLM as Predictor（快速评估策略潜力）
2. **EvolveR 的经验蒸馏**是最值得直接复用的机制：成功策略→提取原则→写回 prompt→指导下轮生成
3. **GodelAgent 的自指涉**提供理论上限：如果 Agent 能改自己的搜索逻辑，就不需要人类设计搜索策略
4. **WALLE 的规则学习**可用于评分函数建模：从多次评测中学习"什么分配模式容易拿高分"的规则
