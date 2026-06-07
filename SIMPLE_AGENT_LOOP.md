# 简单 Agent Loop 架构说明

## 当前结论

项目可以完成离线自迭代，但不建议继续依赖复杂 LangGraph 编排。

当前推荐架构已经收敛为一个顺序 loop：

```text
必要时先做离线研究（本地论文/arXiv/URL）
  -> LLM 选择探索方向并生成 solver
  -> 语法/接口验证
  -> 沙箱运行
  -> 校准数据 DetCov/DetScore 评测
  -> 采纳或丢弃
  -> 写入 runs/、library/、snapshots/
```

入口：

```bash
python search.py
```

或：

```bash
python -m agent
```

默认是 dry-run，不调用 LLM。真实调用 LLM：

```bash
python search.py --live --max-rounds 5
```

## 为什么改成简单 loop

- 赛题核心是持续生成、评测、筛选 `solver.py` 策略，不需要复杂图编排。
- 当前最大风险不是“不会生成代码”，而是“本地指标误导线上结果”。
- 简单 loop 更容易插入强约束：`DetCov=1.0`、避免 cost-first、默认不覆盖 `solver.py`。
- 旧的图编排入口已清理，避免后续维护误入复杂节点架构。

## Loop 给 Agent 的工具

Agent 每轮可以选择研究工具，也可以直接生成 solver：

- `read_local_papers(query)`：检索 `papers/*.txt`，提取相关论文片段。
- `arxiv_search(query)`：通过 arXiv API 搜索外部论文，不需要 API key。
- `web_fetch_url(url)`：抓取一个已知 URL 的正文摘要，不做泛搜索。
- `generate_solver`：选择探索方向，输出完整 `solve(input_text: str) -> list` 代码。

此外，loop 会预加载 `agent/skills/*.md` 的描述，并按上下文动态加载少量 skill 正文。查看 skill：

```bash
python search.py --list-skills
```

显式指定 skill：

```bash
python search.py --live --skill scarce_repair --max-rounds 5
```

本地程序提供确定性工具：

- 静态验证：`compile`、`solve` 存在性检查。
- 沙箱运行：超时保护、返回格式检查。
- 校准评测：多 preset 的 `DetCov` 和 `DetScore`。
- 采纳判断：全覆盖且平均 DetScore 明显优于当前 best。
- 持久化：写 `runs/<id>/events.jsonl`、`iterations.jsonl`、`research.md`、`summary.json`、策略库和快照。

## 安全默认值

- 默认不联网、不调 LLM。
- 默认不覆盖根目录 `solver.py`。
- 只有显式传 `--export-best`，采纳的新 best 才会覆盖 `solver.py`。
- `solver.py` 仍必须保持零第三方依赖；离线依赖只允许出现在 Agent 路径。

## 运行示例

dry-run 自检：

```bash
python search.py --max-rounds 1
```

真实 LLM 搜索，不覆盖线上提交物：

```bash
python search.py --live --max-rounds 10 --eval-seeds 1
```

真实 LLM 搜索，并在第一轮先做外部/本地研究：

```bash
python search.py --live --initial-research --max-rounds 10
```

连续 2 轮没有采纳就研究一次：

```bash
python search.py --live --research-on-stall 2 --max-rounds 20
```

真实 LLM 搜索，并在本地校准指标改善时覆盖 `solver.py`：

```bash
python search.py --live --max-rounds 10 --export-best
```

## 当前关键限制

本地校准评测不是线上评测。V44 已证明：

- 本地 DetScore 显著下降；
- 线上平均惩罚却退化到 1,958.27；
- 根因是“按本地最低 cost 择优”退化成 cost-first 反模式。

因此，simple loop 可以完成自迭代，但自动采纳只能作为候选筛选。真正替换线上提交物前，仍需要线上评测确认。

## 全链路日志

每次运行都会创建 `runs/<run_id>/`：

- `events.jsonl`：全链路事件流，面向可视化。事件包括 `run_start`、`round_start`、`research_decision`、`tool_call`、`skill_selection`、`generation`、`validation`、`evaluation`、`accepted`、`round_end`、`run_end`。
- `iterations.jsonl`：每轮策略摘要，面向人工复盘。
- `research.md`：研究工具返回的论文/网页摘要。
- `round_*.py`：每轮候选代码和验证/修复后的代码。
- `summary.json`：最终 best、指标、token 用量和 run 目录。

可视化时优先读取 `events.jsonl`，再按事件里的 `candidate_path`、`validated_path`、`snapshot_py` 关联代码文件。

## 生命周期 Hook

`agent/hooks.py` 提供轻量 Hook 系统。默认 Hook 会把所有事件写入 `events.jsonl`。

Hook 函数签名：

```python
def my_hook(event_type: str, payload: dict, context: HookContext) -> None:
    ...
```

注册方式：

```bash
python search.py --max-rounds 1 --hook agent.sample_hooks:register_hooks
```

也可以注册单个 Hook 函数；如果函数用 `@hook("event_name")` 标注，就监听对应事件，否则默认监听所有事件。

核心生命周期事件：

- `run_start`
- `round_start`
- `research_decision`
- `tool_call`
- `skill_selection`
- `generation`
- `validation`
- `evaluation`
- `accepted`
- `round_end`
- `run_end`

示例文件：[agent/sample_hooks.py](agent/sample_hooks.py) 会在 `evaluation` 事件写 `metrics.jsonl`，在 `accepted` 事件写 `accepted.md`。

## Skill 文件格式

Skill 是 Markdown 文件，放在 `agent/skills/`：

```markdown
---
id: scarce_repair
name: 稀缺场景局部修复
description: 只修改 courier/task 比例低的稀缺场景。
triggers: scarce, 稀缺, backup
---

# 适用场景

# 设计原则

# 反模式
```

loop 启动时只预加载 `id/name/description/triggers`，每轮按上下文匹配后才加载正文，避免 prompt 过长。

默认情况下，Agent 不会自己写 skill。需要显式开启：

```bash
python search.py --live --allow-skill-write --skill-write-on-stall 4 --max-rounds 20
```

触发后，Agent 只会写 Markdown skill 到 `agent/skills/`，不会写 Python 插件；新 skill 会在下一轮被重新预加载描述。
