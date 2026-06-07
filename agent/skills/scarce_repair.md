---
id: scarce_repair
name: 稀缺场景局部修复
description: 只修改 courier/task 比例低的稀缺场景，保持正常/低意愿/任务数分流路径不变。
scope: project
triggers: scarce, 稀缺, backup, c/t, 覆盖不足, scarce_couriers
---

# 适用场景

当 `scarce_couriers` 或 `courier_task_ratio < 0.8` 场景存在成本或覆盖问题时使用。

# 设计原则

- 不要改正常场景、低意愿场景、小/中/大任务数分流。
- 保留主覆盖阶段的集合覆盖思想：优先选能覆盖更多未覆盖任务且 willingness 高的合单。
- 备份阶段必须节制：只有稀缺场景才考虑备份，且最多 1-3 个。
- 备份排序优先考虑 `marginal_gain / score`，不要只看 marginal gain。
- 如果本地指标改善只发生在 `scarce`，这是相对安全的候选；如果正常场景变化，风险更高。

# 生成代码要求

- 基于当前 best solver 做小改动。
- 保留原始 `task_id_list_str` 或确保 `",".join(task_ids)` 能匹配输入候选。
- 不要引入 import。
