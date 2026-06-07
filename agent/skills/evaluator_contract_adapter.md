---
id: evaluator_contract_adapter
name: 评测契约适配
description: 通用流程：把用户目标、评测集、评测脚本或 LLM-as-judge 需求规范化为统一评测契约。
scope: generic
triggers: evaluator, dataset, metric, judge, contract, rubric, llm as judge
---

# 适用场景

当项目换成新的评测集、指标、接口或没有显式标签时使用。

# 操作步骤

1. 先识别输入数据结构、目标文件、入口函数和输出格式。
2. 如果用户提供评测脚本，只把它作为材料检查和适配，不直接执行不可信命令。
3. 把任意评测返回值统一成 `{ok, primary_score, hard_pass, metrics, feedback}`。
4. 如果没有评测集或标签，启用 LLM-as-judge 草案，并要求用户提供 rubric 或好坏倾向。
5. 在 agent run 目录保存契约，后续迭代都基于同一个契约。

# 约束

- 不要求用户脚本必须提前按固定函数名书写。
- 适配脚本必须先试运行和展示给用户手改。
- 本地 Web 不直接执行用户给的任意 shell 命令。
