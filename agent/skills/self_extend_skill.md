---
id: self_extend_skill
name: 自我扩展 Skill
description: 当现有 skill 不够时，提出一个新的 skill 草案，供人工或显式开关写入。
scope: system
triggers: self improve, skill, tool, 自我扩展, 加工具, 架构
---

# 适用场景

当 Agent 发现自己反复失败，且失败不是 solver 代码细节，而是缺少某类能力时使用。

# Skill 草案格式

输出一个 Markdown skill 草案：

```markdown
---
id: short_id
name: 中文名
description: 这个 skill 解决什么问题
triggers: keyword1, keyword2
---

# 适用场景

# 操作步骤

# 反模式
```

# 注意

- 默认只提出草案，不自动写入。
- 只有主 loop 显式允许写入 skill 时，才能落盘。
