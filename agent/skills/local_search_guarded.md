---
id: local_search_guarded
name: 受保护局部搜索
description: 从当前 best 解出发，只接受保持 DetCov=1.0 且降低成本的局部替换。
scope: generic
triggers: local search, repair, swap, replace, 2-opt, 局部搜索, 替换
---

# 适用场景

当贪心解已经很强，但需要寻找小幅改进时使用。

# 设计原则

- 先构造当前 best 的主解。
- 构建未使用骑手和已覆盖任务索引。
- 尝试单点替换或小范围交换，但必须满足：
  - 所有订单仍覆盖；
  - 每个骑手最多使用一次；
  - 新候选必须存在于输入候选表；
  - 总 score 严格下降才接受。
- 限制搜索规模，避免 10 秒超时。

# 反模式

- 不要全局按最低 cost 重选，那会退化成 cost-first。
- 不要为了本地 DetScore 破坏 V9 的 willingness 分桶多样性。
