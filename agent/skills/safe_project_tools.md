---
id: safe_project_tools
name: 安全项目工具
description: 通用约束：agent 可以读写项目内文件、生成分析脚本并执行，但不能越出项目目录或执行任意 shell。
scope: generic
triggers: tools, sandbox, file access, python script, project root, safety
---

# 适用场景

当 agent 需要自己选择工具、查看文件、写分析脚本、执行脚本时使用。

# 规则

- 所有路径必须 resolve 在项目根目录内。
- 默认写入 `runs/<run_id>/tool_scripts/`，不要污染源码目录。
- 执行只允许 Python 脚本，且不通过 shell 拼接命令。
- 工具调用必须记录 reason、purpose、params、summary 和 artifacts。
- 工具结果应该进入下一轮 prompt，也应该进入可视化事件流。

# 反模式

- 不要开放任意 `cmd` / `powershell` / `bash` 给 Web 用户。
- 不要让最终目标文件依赖 agent 工具层。
- 不要让分析脚本读取项目目录外的路径。
