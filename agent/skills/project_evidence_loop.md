---
id: project_evidence_loop
name: 项目证据循环
description: 通用流程：先读项目状态和历史评测，再写小脚本验证假设，最后把证据注入下一轮改动。
scope: generic
triggers: evidence, replay, history, evaluation, analysis script, project tools, tool_scripts
---

# 适用场景

适用于任何需要自迭代改进单文件或小模块的项目，不绑定具体赛题。

# 操作步骤

1. 读取当前目标文件和最近评测结果。
2. 如果已有历史结果，先写一个小型 replay/analysis 脚本，把关键指标按时间顺序打印出来。
3. 执行脚本，确认假设来自真实数据，而不是凭记忆。
4. 每轮只提出一个可验证改动。
5. 把失败原因、成功经验和脚本输出写回下一轮上下文。

# 约束

- 工具读写和脚本执行必须限制在项目目录内。
- 分析脚本只用于离线研究，不允许进入最终提交文件。
- 不要跳过验证直接修改目标文件。
