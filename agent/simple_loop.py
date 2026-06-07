"""简单 AutoResearch Agent loop。

目标：不用 LangGraph，只保留一个可读、可追踪的离线自迭代循环。

每轮流程：
1. 让 LLM 基于工具说明和历史结果选择探索方向并生成 solver 代码。
2. 用沙箱验证语法、接口、运行和返回格式。
3. 在校准数据集上做确定性覆盖/成本评测。
4. 若全覆盖且平均 DetScore 明显优于当前 best，则入库并存快照。

注意：默认不覆盖线上提交文件 solver.py；需要显式传 --export-best。
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

from agent.dry_run_templates import build_strategy_code
from agent.llm_client import LLMClient, generate_dry_run_strategy
from agent.hooks import build_default_hook_manager, load_hook_specs
from agent.project_tools import (
    ProjectToolExecutor,
    run_default_project_tool_sequence,
)
from agent.research_tools import (
    append_research_markdown,
    arxiv_search,
    format_research_result,
    read_local_papers,
    web_fetch_url,
)
from agent.run_logging import append_jsonl, ensure_run_directory, new_run_id
from agent.sandbox import (
    _clean_code,
    extract_solve,
    plan_format_errors,
    run_on_data,
    try_fix_with_usage,
    validate_syntax,
)
from agent.settings import merge_runtime_bundle
from agent.skills import (
    discover_skills,
    format_selected_skills,
    format_skill_catalog,
    select_skills,
    write_skill,
)
from data_generator import CALIBRATED_PRESETS, generate
from judge import evaluate_deterministic
from library.store import add_strategy, archive_solver_snapshot, update_performance
from parser import parse


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASELINE = REPO_ROOT / "solver.py"
DEFAULT_PRESETS = [
    "calibrated_tiny",
    "calibrated_small",
    "calibrated_medium",
    "calibrated_large",
    "calibrated_scarce",
    "calibrated_low_will",
    "calibrated_high_noise",
]


SIMPLE_SYSTEM_PROMPT = """你是一个离线算法搜索 Agent，目标是为配送订单-骑手匹配问题生成一个可提交的 solver.py。

你每轮只能使用一个工具：`generate_solver`。
工具职责：选择一个探索方向，并输出完整 Python 代码。代码必须包含 solve(input_text: str) -> list。

可选探索方向：
- route_threshold_tuning：微调 V9 的场景分流阈值。
- bucket_sort_variant：改进 willingness 分桶或桶内排序。
- scarce_branch_only：只改稀缺场景，保持正常场景不动。
- guarded_local_repair：从 V9 解出发，只做能证明降低成本且保持覆盖的局部替换。
- exact_small_case：仅对小任务场景做可控精确/束搜索，其余场景保持 V9。
- new_paradigm：尝试新的轻量建模，但必须在 10 秒内完成。

已知反模式，必须避免：
- cost_first 或单纯选择 total_score 最低会线上大幅退化。
- 多策略组合后按本地 DetScore 最低择优，在线上可能退化成 cost_first，V44 已失败。
- 大量备份在确定性覆盖已满时只会增加线上成本。
- 不能 import 项目内部模块，不能依赖第三方库。

输入解析必须严格遵守：
- 输入是 TSV 文本，首行可能是 header：task_id_list\tcourier_id\ttotal_score\twillingness。
- 如果第一行以 "task_id_list" 开头，必须从第二行开始解析。
- task_id 是字符串，形如 T0001；courier_id 是字符串，形如 C0001。绝对不要把 task_id 或 courier_id 转成 int。
- task_id_list 可能是 "T0001,T0002"，必须 split(",") 后按字符串处理。
- total_score 和 willingness 才能转 float。
- willingness <= 0 的候选必须跳过。
- 返回必须是 [(task_id_list_str, [courier_id]), ...]，顺序不能写反。
- 同一个 courier_id 只能出现一次；同一个订单也不能被多个主分配重复覆盖。
- 不要 print 调试信息；不要写读取 stdin、文件或网络的代码。

建议直接复用这个解析骨架，避免表头错误：
```
lines = input_text.strip().splitlines()
start = 1 if lines and lines[0].startswith("task_id_list") else 0
for line in lines[start:]:
    parts = line.strip().split("\\t")
    if len(parts) < 4:
        continue
    task_id_list_str, courier_id, score_str, willingness_str = parts[:4]
    score = float(score_str)
    willingness = float(willingness_str)
    task_ids = tuple(t.strip() for t in task_id_list_str.split(",") if t.strip())
```

输出要求：
只输出 Python 代码。文件顶部写：
# Strategy: <短策略名>
# Direction: <上面方向之一>
# Rationale: <一句话原因>
"""


def _strategy_name_from_code(code: str, fallback: str) -> str:
    for line in code.splitlines()[:20]:
        if line.startswith("# Strategy:"):
            name = line.split(":", 1)[1].strip()
            if name:
                return name
    return fallback


def _code_header_summary(code: str) -> dict[str, str]:
    """提取候选 solver 顶部声明，供可视化展示本轮改动意图。"""
    summary = {"strategy": "", "direction": "", "rationale": ""}
    for line in code.splitlines()[:40]:
        if line.startswith("# Strategy:"):
            summary["strategy"] = line.split(":", 1)[1].strip()
        elif line.startswith("# Direction:"):
            summary["direction"] = line.split(":", 1)[1].strip()
        elif line.startswith("# Rationale:"):
            summary["rationale"] = line.split(":", 1)[1].strip()
    return summary


def _strict_plan_errors(plan: object, data) -> str | None:
    fmt = plan_format_errors(plan)
    if fmt:
        return fmt

    assert isinstance(plan, list)
    used_couriers = set()
    for idx, (task_str, courier_list) in enumerate(plan):
        task_ids = tuple(t.strip() for t in task_str.split(",") if t.strip())
        if not task_ids:
            return f"下标 {idx}: task_id_list 为空"
        for cid in courier_list:
            if cid in used_couriers:
                return f"重复骑手: {cid}"
            used_couriers.add(cid)
            if data.get_candidate(task_ids, cid) is None:
                return f"无效候选: {task_str} / {cid}"
    return None


def _eval_plan(plan: list, raw: str) -> dict[str, Any]:
    data = parse(raw)
    strict = _strict_plan_errors(plan, data)
    if strict:
        return {"ok": False, "error": strict}
    det = evaluate_deterministic(plan, data)
    return {
        "ok": True,
        "det_cov": det.coverage_rate,
        "det_score": det.total_score,
        "uncovered": det.uncovered_tasks,
        "entries": len(plan),
    }


def evaluate_code(code: str, *, eval_seeds: int, timeout: float) -> dict[str, Any]:
    """沙箱评测生成代码。"""
    rows = []
    for preset_name in DEFAULT_PRESETS:
        preset = CALIBRATED_PRESETS[preset_name]
        for seed in range(eval_seeds):
            params = dict(preset["params"])
            params["seed"] = seed
            raw = generate(**params)
            run = run_on_data(code, raw, timeout=timeout)
            if not run.get("ok"):
                rows.append({
                    "ok": False,
                    "preset": preset_name,
                    "seed": seed,
                    "error": run.get("error", "运行失败"),
                })
                continue
            row = _eval_plan(run.get("result"), raw)
            row.update({
                "preset": preset_name,
                "seed": seed,
                "elapsed": run.get("elapsed", 0.0),
            })
            rows.append(row)
    return _summarize_rows(rows)


def _summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    failures = [r for r in rows if not r.get("ok")]
    ok_rows = [r for r in rows if r.get("ok")]
    if not rows or failures:
        return {
            "ok": False,
            "rows": rows,
            "error": failures[0].get("error", "评测失败") if failures else "无评测数据",
        }

    avg_det = sum(float(r["det_score"]) for r in ok_rows) / len(ok_rows)
    min_cov = min(float(r["det_cov"]) for r in ok_rows)
    avg_time = sum(float(r.get("elapsed", 0.0)) for r in ok_rows) / len(ok_rows)
    return {
        "ok": True,
        "rows": rows,
        "avg_det_score": avg_det,
        "min_det_cov": min_cov,
        "avg_time_ms": avg_time * 1000.0,
        "all_full_cov": min_cov >= 0.999,
    }


def _format_metric(m: dict[str, Any]) -> str:
    if not m.get("ok"):
        return f"FAIL: {m.get('error')}"
    return (
        f"avg_det={m['avg_det_score']:.2f}, "
        f"min_cov={m['min_det_cov']:.3f}, "
        f"avg_time_ms={m['avg_time_ms']:.1f}"
    )


def _load_evaluation_contract(path_text: str | None) -> dict[str, Any] | None:
    if not path_text:
        return None
    path = Path(path_text)
    if not path.is_absolute():
        path = REPO_ROOT / path
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _run_llm_judge(
    *,
    llm: LLMClient,
    dry_run: bool,
    contract: dict[str, Any] | None,
    baseline_name: str,
    baseline_code: str,
    candidate_name: str,
    candidate_code: str,
    metrics: dict[str, Any],
    round_no: int,
) -> tuple[dict[str, Any] | None, int]:
    """用同一个 LLMClient 执行 LLM-as-judge 评测补充。"""
    evaluator = contract.get("evaluator") if isinstance(contract, dict) else None
    if not isinstance(evaluator, dict) or evaluator.get("type") != "llm_as_judge":
        return None, 0
    if dry_run:
        return {
            "ok": False,
            "mode": "dry-run",
            "summary": "dry-run 模式不调用 LLM-as-judge。",
        }, 0

    rubric = str(evaluator.get("rubric") or contract.get("user_goal") or "").strip()
    direction = str((contract.get("metrics") or {}).get("direction") or "maximize")
    prompt = {
        "round": round_no,
        "task": "Compare candidate solver against baseline under the rubric. Return strict JSON only.",
        "rubric": rubric,
        "metric_direction": direction,
        "local_metrics": metrics,
        "baseline": {
            "name": baseline_name,
            "code_head": baseline_code[:9000],
        },
        "candidate": {
            "name": candidate_name,
            "code_head": candidate_code[:9000],
        },
        "required_json_schema": {
            "ok": "boolean",
            "hard_pass": "boolean",
            "primary_score": "number 0-100, higher means better unless metric_direction says otherwise",
            "preference": "candidate|baseline|tie",
            "summary": "short Chinese explanation",
            "risks": ["short risk strings"],
            "use_for_acceptance": False,
        },
    }
    res = llm.complete(
        [
            {
                "role": "system",
                "content": "你是严谨的 LLM-as-judge。只输出 JSON，不要 Markdown。重点检查候选方案是否满足目标、硬约束和可上线风险。",
            },
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ],
        temperature=0.1,
        max_tokens=1200,
    )
    if res is None or not res.content:
        return {
            "ok": False,
            "summary": "LLM-as-judge 无输出。",
        }, int(res.total_tokens if res else 0)
    try:
        parsed = json.loads(res.content)
        if isinstance(parsed, dict):
            parsed.setdefault("ok", True)
            parsed.setdefault("use_for_acceptance", False)
            return parsed, int(res.total_tokens or 0)
    except json.JSONDecodeError:
        pass
    return {
        "ok": False,
        "summary": "LLM-as-judge 返回不是合法 JSON。",
        "raw_preview": res.content[:1000],
    }, int(res.total_tokens or 0)


def _build_round_summary(
    *,
    record: dict[str, Any],
    previous_best_name: str,
    previous_best_metrics: dict[str, Any],
    current_best_name: str,
    current_best_metrics: dict[str, Any],
    llm_judge: dict[str, Any] | None,
) -> str:
    metrics = record.get("metrics") or {}
    status = "采纳" if record.get("accepted") else "未采纳"
    metric_text = record.get("metrics_text") or _format_metric(metrics)
    parts = [
        f"本轮策略 {record.get('name')} {status}。",
        f"本轮指标：{metric_text}。",
        f"判断理由：{record.get('reason', '无')}。",
    ]
    if previous_best_name != current_best_name:
        parts.append(f"best 已从 {previous_best_name} 更新为 {current_best_name}。")
    else:
        parts.append(f"best 保持 {current_best_name}，当前 best 指标：{_format_metric(current_best_metrics)}。")
    if llm_judge:
        parts.append(f"LLM-as-judge：{llm_judge.get('summary') or llm_judge.get('preference') or '已完成补充判断'}。")
    if metrics.get("ok") and previous_best_metrics.get("ok"):
        delta = float(metrics.get("avg_det_score", 0.0)) - float(previous_best_metrics.get("avg_det_score", 0.0))
        parts.append(f"经验：本轮相对上一 best 的 avg_det 变化为 {delta:+.2f}，下一轮应优先保护满覆盖并只做可解释小改动。")
    return " ".join(parts)


def _build_generation_prompt(
    *,
    best_metrics: dict[str, Any],
    best_code: str,
    research_context: str,
    skill_catalog: str,
    selected_skill_text: str,
    attempts: list[dict[str, Any]],
    round_no: int,
    metric_hints: str | None,
) -> str:
    lines = [
        f"## Round {round_no}",
        "当前 best 是线上验证过的 V9 风格 solver，不能轻易破坏正常场景。",
        f"当前 best 本地校准指标: {_format_metric(best_metrics)}",
        "本轮若无法保证覆盖全部订单，请宁可保守改动，不要为了本地 cost 牺牲覆盖或线上鲁棒性。",
        "",
        "## 最近尝试",
    ]
    if attempts:
        for a in attempts[-5:]:
            lines.append(
                f"- {a.get('name')}: accepted={a.get('accepted')} "
                f"{a.get('metrics_text')} reason={a.get('reason', '')}"
            )
    else:
        lines.append("- 无。")

    if metric_hints:
        lines += ["", "## 指标提示", metric_hints.strip()]

    if research_context.strip():
        lines += [
            "",
            "## 最近研究摘要",
            "下面是离线研究工具得到的算法线索。请把它转化为可提交 solver 的小范围改动；不要照抄复杂库依赖。",
            research_context[-9000:],
        ]

    if skill_catalog.strip():
        lines += [
            "",
            "## 可用 Skill 描述（预加载）",
            skill_catalog,
        ]

    if selected_skill_text.strip():
        lines += [
            "",
            "## 本轮已加载 Skill",
            selected_skill_text,
        ]

    lines += [
        "",
        "请选择一个探索方向，生成完整 solver 代码。",
        "强建议：优先做小范围、可解释、不会退化成 cost_first 的改动。",
        "禁止把 task_id_list 或 courier_id 当整数处理；上一波失败的主要原因就是表头/ID 解析错误。",
        "",
        "## 当前 best solver.py 源码",
        "你必须以这份代码为基础做小改动，不要从零重写解析器和返回格式。",
        "如果新增候选字段，请保留原始 task_id_list_str 用于返回，避免返回不存在的候选。",
        "```python",
        best_code[:12000],
        "```",
    ]
    return "\n".join(lines)


def _generate_code(
    *,
    llm: LLMClient,
    dry_run: bool,
    best_metrics: dict[str, Any],
    best_code: str,
    research_context: str,
    skill_catalog: str,
    selected_skill_text: str,
    attempts: list[dict[str, Any]],
    round_no: int,
    metric_hints: str | None,
) -> tuple[str, int]:
    if dry_run:
        spec = generate_dry_run_strategy()
        return build_strategy_code(spec), 0

    prompt = _build_generation_prompt(
        best_metrics=best_metrics,
        best_code=best_code,
        research_context=research_context,
        skill_catalog=skill_catalog,
        selected_skill_text=selected_skill_text,
        attempts=attempts,
        round_no=round_no,
        metric_hints=metric_hints,
    )
    res = llm.complete(
        [
            {"role": "system", "content": SIMPLE_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    )
    if res is None or not res.content:
        return "", int(res.total_tokens if res else 0)
    return _clean_code(res.content), int(res.total_tokens or 0)


def _validate_and_maybe_repair(
    *,
    code: str,
    llm: LLMClient,
    dry_run: bool,
    max_repair_attempts: int,
) -> tuple[str, str, int]:
    """返回 (code, error, token_delta)。error 为空表示通过静态验证。"""
    token_delta = 0
    current = code

    for _ in range(max(1, max_repair_attempts + 1)):
        ok, err = validate_syntax(current)
        if not ok:
            kind = "syntax"
        else:
            ok, err = extract_solve(current)
            kind = "exec"
        if ok:
            return current, "", token_delta
        if dry_run or max_repair_attempts <= 0:
            return current, err, token_delta
        fixed, used, attempts = try_fix_with_usage(
            llm,
            current,
            err,
            max_retries=1,
            error_kind=kind,
        )
        token_delta += int(used)
        max_repair_attempts -= attempts
        if not fixed:
            return current, err, token_delta
        current = fixed

    return current, "修复次数耗尽", token_delta


def _accept(metrics: dict[str, Any], best_metrics: dict[str, Any], min_delta: float) -> tuple[bool, str]:
    if not metrics.get("ok"):
        return False, str(metrics.get("error", "评测失败"))
    if not metrics.get("all_full_cov"):
        return False, f"DetCov 未满: {metrics.get('min_det_cov')}"
    delta = float(metrics["avg_det_score"]) - float(best_metrics["avg_det_score"])
    if delta < -float(min_delta):
        return True, f"avg_det 改善 {delta:.2f}"
    return False, f"avg_det 未改善: {delta:+.2f}"


def _repair_after_eval_failure(
    *,
    code: str,
    name: str,
    metrics: dict[str, Any],
    llm: LLMClient,
    dry_run: bool,
    timeout: float,
    eval_seeds: int,
) -> tuple[str, dict[str, Any], int]:
    """对格式、重复骑手、运行输出等可修复失败追加一次修复评测。"""
    if dry_run or metrics.get("ok"):
        return code, metrics, 0

    error = str(metrics.get("error", "评测失败"))
    fix_prompt = (
        f"策略 {name} 在本地评测失败，错误：{error}\n"
        "请只修复代码，不要改变为全新策略。必须满足：\n"
        "1. solve(input_text: str) -> list\n"
        "2. 返回 [(task_id_list_str, [courier_id]), ...]\n"
        "3. task_id/courier_id 都是字符串，不能转 int\n"
        "4. 每个 courier_id 最多出现一次\n"
        "5. 不要 print 调试信息\n"
    )
    fixed, used, _attempts = try_fix_with_usage(
        llm,
        code,
        fix_prompt,
        max_retries=1,
        error_kind="format",
    )
    if not fixed:
        return code, metrics, int(used)
    return fixed, evaluate_code(fixed, eval_seeds=eval_seeds, timeout=timeout), int(used)


RESEARCH_SYSTEM_PROMPT = """你是算法研究调度器。你只能输出一个 JSON 对象，不要 Markdown。

可选工具：
- read_local_papers: 检索仓库 papers/*.txt。适合先读已有论文库。
- arxiv_search: 搜索 arXiv。适合寻找 set packing、local search、LNS、beam search、hypergraph matching 等外部算法。
- web_fetch_url: 抓取一个已知 URL。只有当你能给出明确 URL 时才用。
- generate_solver: 本轮不研究，直接生成 solver。

JSON 格式：
{"tool":"read_local_papers|arxiv_search|web_fetch_url|generate_solver","query":"...","url":"...","reason":"..."}
"""


def _safe_json_object(text: str | None) -> dict[str, Any] | None:
    if not text:
        return None
    text = text.strip()
    if text.startswith("```"):
        text = text.replace("```json", "").replace("```", "").strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start:end + 1]
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def _stalled_rounds(attempts: list[dict[str, Any]]) -> int:
    n = 0
    for item in reversed(attempts):
        if item.get("accepted"):
            break
        n += 1
    return n


def _should_research(args: argparse.Namespace, attempts: list[dict[str, Any]], round_no: int) -> bool:
    if args.no_research:
        return False
    if args.initial_research and round_no == 1:
        return True
    if args.research_every and args.research_every > 0 and round_no > 1:
        return (round_no - 1) % args.research_every == 0
    if args.research_on_stall and args.research_on_stall > 0:
        return _stalled_rounds(attempts) >= args.research_on_stall
    return False


def _choose_research_call(
    *,
    llm: LLMClient,
    dry_run: bool,
    best_metrics: dict[str, Any],
    attempts: list[dict[str, Any]],
    research_context: str,
) -> tuple[dict[str, Any], int]:
    if dry_run:
        return {
            "tool": "read_local_papers",
            "query": "k-set packing local search large neighborhood search assignment heuristic",
            "reason": "dry-run 默认检索本地论文库",
        }, 0

    prompt = {
        "best_metrics": _format_metric(best_metrics),
        "recent_attempts": [
            {
                "name": a.get("name"),
                "accepted": a.get("accepted"),
                "reason": a.get("reason"),
                "metrics": a.get("metrics_text"),
            }
            for a in attempts[-6:]
        ],
        "research_context_tail": research_context[-3000:],
        "task": (
            "我们卡在 V9 风格贪心框架附近。请选择一个研究工具，寻找能转化为纯 Python "
            "solver 的突破方向。优先研究 k-set packing、weighted set packing、"
            "large neighborhood search、beam search、matheuristic、hypergraph matching。"
        ),
    }
    res = llm.complete(
        [
            {"role": "system", "content": RESEARCH_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ],
        temperature=0.2,
        max_tokens=700,
    )
    obj = _safe_json_object(res.content if res else None)
    if obj is None:
        obj = {
            "tool": "read_local_papers",
            "query": "weighted k-set packing local search heuristic",
            "reason": "LLM 工具选择无法解析，回退本地论文检索",
        }
    return obj, int(res.total_tokens if res else 0)


def _run_research_tool(call: dict[str, Any]) -> dict[str, Any]:
    tool = str(call.get("tool") or "read_local_papers").strip()
    query = str(call.get("query") or "").strip()
    url = str(call.get("url") or "").strip()

    if tool == "generate_solver":
        return {
            "tool": "generate_solver",
            "query": query,
            "summary": "Agent chose to skip research this round.",
            "reason": call.get("reason", ""),
        }
    if tool == "arxiv_search":
        return arxiv_search(query or "weighted k-set packing heuristic local search")
    if tool == "web_fetch_url":
        if not url:
            return {
                "tool": "web_fetch_url",
                "url": "",
                "error": "未提供 URL",
                "summary": "",
            }
        return web_fetch_url(url)
    return read_local_papers(query or "weighted k-set packing local search heuristic")


PROJECT_TOOL_SYSTEM_PROMPT = """You are a project-local tool planner for an AutoResearch loop.
Return only one JSON object. Do not return Markdown.

Allowed tools:
- list_files: {"pattern":"*.py","limit":80}
- read_file: {"path":"solver.py","max_chars":12000}
- analyze_online_results: {"limit":8}
- write_analysis_script: {"filename":"round_analysis.py","code":"print('...')"}
- run_python: {"path":"runs/<id>/tool_scripts/round_analysis.py","args":[],"timeout":30}
- stop: {}

Hard constraints:
- Every path is restricted to the repository root by the executor.
- Do not request shell commands.
- Prefer analysis scripts that inspect evaluations/*.json, solver.py, snapshots, or local eval scripts.
- Stop once you have enough evidence for the next solver edit.

JSON format:
{"tool":"...","params":{...},"reason":"why this action is needed","purpose":"what decision this action informs"}
"""


def _choose_project_tool_call(
    *,
    llm: LLMClient,
    best_metrics: dict[str, Any],
    attempts: list[dict[str, Any]],
    tool_context: str,
    round_no: int,
    step_no: int,
) -> tuple[dict[str, Any], int]:
    prompt = {
        "round": round_no,
        "step": step_no,
        "best_metrics": _format_metric(best_metrics),
        "recent_attempts": [
            {
                "name": a.get("name"),
                "accepted": a.get("accepted"),
                "reason": a.get("reason"),
                "metrics": a.get("metrics_text"),
            }
            for a in attempts[-5:]
        ],
        "tool_context_tail": tool_context[-6000:],
        "task": (
            "Choose one project-local tool call that helps reproduce the solver iteration process: "
            "inspect files, replay online results, write a small Python analysis script, execute it, "
            "or stop if enough evidence has been gathered."
        ),
    }
    res = llm.complete(
        [
            {"role": "system", "content": PROJECT_TOOL_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ],
        temperature=0.2,
        max_tokens=1400,
    )
    obj = _safe_json_object(res.content if res else None)
    if obj is None:
        obj = {
            "tool": "analyze_online_results",
            "params": {"limit": 6},
            "reason": "fallback after invalid tool JSON",
            "purpose": "recover recent online evidence before solver generation",
        }
    return obj, int(res.total_tokens if res else 0)


def _execute_project_tool(executor: ProjectToolExecutor, call: dict[str, Any]):
    tool = str(call.get("tool") or "analyze_online_results").strip()
    params = call.get("params") if isinstance(call.get("params"), dict) else {}
    reason = str(call.get("reason") or "")
    purpose = str(call.get("purpose") or "")
    if tool == "list_files":
        return executor.list_files(
            pattern=str(params.get("pattern") or "*.py"),
            limit=int(params.get("limit") or 80),
            reason=reason,
            purpose=purpose,
        )
    if tool == "read_file":
        return executor.read_file(
            path=str(params.get("path") or "solver.py"),
            max_chars=int(params.get("max_chars") or 12000),
            reason=reason,
            purpose=purpose,
        )
    if tool == "write_analysis_script":
        return executor.write_analysis_script(
            filename=str(params.get("filename") or "round_analysis.py"),
            code=str(params.get("code") or "print('empty analysis script')"),
            reason=reason,
            purpose=purpose,
        )
    if tool == "run_python":
        raw_args = params.get("args")
        return executor.run_python(
            path=str(params.get("path") or ""),
            args=[str(x) for x in raw_args] if isinstance(raw_args, list) else [],
            timeout=float(params.get("timeout") or 30.0),
            reason=reason,
            purpose=purpose,
        )
    return executor.analyze_online_results(
        limit=int(params.get("limit") or 8),
        reason=reason,
        purpose=purpose,
    )


def _run_project_tool_cycle(
    *,
    args: argparse.Namespace,
    llm: LLMClient,
    dry_run: bool,
    run_dir: Path,
    hooks,
    round_no: int,
    best_metrics: dict[str, Any],
    attempts: list[dict[str, Any]],
) -> tuple[str, int]:
    if not getattr(args, "enable_project_tools", False):
        return "", 0

    executor = ProjectToolExecutor(REPO_ROOT, run_dir)
    context_chunks: list[str] = []
    tokens = 0

    if dry_run or getattr(args, "project_tool_warmup", False):
        for result in run_default_project_tool_sequence(executor, round_no):
            hooks.emit("tool_call", result.as_event_payload(round_no))
            context_chunks.append(result.format_for_prompt())
            print(f"  [project-tool] {result.tool}: {'ok' if result.ok else result.error}")
        if dry_run:
            return "\n\n".join(context_chunks), tokens

    for step_no in range(1, max(0, int(args.project_tool_steps)) + 1):
        call, used = _choose_project_tool_call(
            llm=llm,
            best_metrics=best_metrics,
            attempts=attempts,
            tool_context="\n\n".join(context_chunks),
            round_no=round_no,
            step_no=step_no,
        )
        tokens += used
        tool = str(call.get("tool") or "")
        hooks.emit("project_tool_decision", {
            "round": round_no,
            "step": step_no,
            "call": call,
            "reason": call.get("reason"),
            "purpose": call.get("purpose"),
            "tokens_used_delta": used,
        })
        if tool == "stop":
            break
        result = _execute_project_tool(executor, call)
        hooks.emit("tool_call", result.as_event_payload(round_no))
        context_chunks.append(result.format_for_prompt())
        print(f"  [project-tool] {result.tool}: {'ok' if result.ok else result.error}")

    return "\n\n".join(context_chunks), tokens


SKILL_WRITE_SYSTEM_PROMPT = """你是 Agent skill 设计器。只能输出一个 JSON 对象，不要 Markdown。

目标：根据最近失败，为 AutoResearch Agent 设计一个新的 Markdown skill。

JSON 格式：
{
  "id": "short_snake_id",
  "name": "中文名",
  "description": "一句话描述",
  "scope": "generic|project|system",
  "triggers": ["keyword1", "keyword2"],
  "body": "# 适用场景\\n...\\n# 操作步骤\\n...\\n# 反模式\\n..."
}

要求：
- skill 只能是提示词/流程规约，不能要求执行第三方库或联网代码。
- 内容要能指导下一轮生成纯 Python solver。
- 默认写 generic；只有明显绑定当前项目/赛题时才写 project。
- 不要重复已有 skill。
"""


def _maybe_write_new_skill(
    *,
    args: argparse.Namespace,
    llm: LLMClient,
    dry_run: bool,
    skills_dir: Path,
    skill_catalog_items,
    attempts: list[dict[str, Any]],
    research_context: str,
    hooks,
    round_no: int,
) -> int:
    if dry_run or not args.allow_skill_write:
        return 0
    if args.skill_write_on_stall <= 0:
        return 0
    if _stalled_rounds(attempts) < args.skill_write_on_stall:
        return 0

    prompt = {
        "existing_skills": [s.catalog_line() for s in skill_catalog_items],
        "recent_attempts": [
            {
                "name": a.get("name"),
                "accepted": a.get("accepted"),
                "reason": a.get("reason"),
                "metrics": a.get("metrics_text"),
            }
            for a in attempts[-6:]
        ],
        "research_context_tail": research_context[-4000:],
        "task": "如果现有 skill 不足，请生成一个新的 skill，帮助后续 solver 生成跳出失败模式。",
    }
    res = llm.complete(
        [
            {"role": "system", "content": SKILL_WRITE_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ],
        temperature=0.35,
        max_tokens=1800,
    )
    used = int(res.total_tokens if res else 0)
    obj = _safe_json_object(res.content if res else None)
    if not obj:
        hooks.emit("skill_write", {
            "round": round_no,
            "ok": False,
            "error": "LLM skill JSON 无法解析",
        })
        return used

    try:
        path = write_skill(
            skills_dir,
            sid=str(obj.get("id") or "").strip(),
            name=str(obj.get("name") or "").strip(),
            description=str(obj.get("description") or "").strip(),
            scope=str(obj.get("scope") or "generic").strip(),
            triggers=[str(t) for t in obj.get("triggers", []) if str(t).strip()],
            body=str(obj.get("body") or "").strip(),
        )
    except Exception as e:
        hooks.emit("skill_write", {
            "round": round_no,
            "ok": False,
            "error": f"{type(e).__name__}: {e}",
        })
        return used

    hooks.emit("skill_write", {
        "round": round_no,
        "ok": True,
        "path": str(path),
        "id": obj.get("id"),
        "name": obj.get("name"),
        "description": obj.get("description"),
    })
    print(f"  [skill-write] {path}")
    return used


def run_loop(args: argparse.Namespace) -> dict[str, Any]:
    settings_path = Path(args.settings) if args.settings else None
    cli_llm = {}
    if args.llm_api_key:
        cli_llm["api_key"] = args.llm_api_key
    if args.llm_base_url:
        cli_llm["base_url"] = args.llm_base_url
    if args.llm_model:
        cli_llm["model"] = args.llm_model

    runtime = merge_runtime_bundle(
        settings_file=settings_path,
        cli_llm_patch=cli_llm if cli_llm else None,
    )
    dry_run = not args.live
    if not dry_run and not runtime.llm.api_key.strip():
        print("[simple-loop] 未配置 API key，退回 dry-run")
        dry_run = True

    run_dir = Path(args.run_dir) if args.run_dir else ensure_run_directory(new_run_id())
    run_dir.mkdir(parents=True, exist_ok=True)
    skills_dir = Path(args.skills_dir)
    if not skills_dir.is_absolute():
        skills_dir = REPO_ROOT / skills_dir
    skill_catalog_items = [] if args.no_skills else discover_skills(skills_dir)
    skill_catalog_text = format_skill_catalog(skill_catalog_items)

    if args.list_skills:
        print(skill_catalog_text)
        return {
            "skills": [s.id for s in skill_catalog_items],
            "run_dir": str(run_dir),
        }
    evaluation_contract = _load_evaluation_contract(args.evaluation_contract)

    baseline_path = Path(args.baseline)
    if not baseline_path.is_absolute():
        baseline_path = REPO_ROOT / baseline_path
    best_code = baseline_path.read_text(encoding="utf-8")
    best_name = _strategy_name_from_code(best_code, "baseline")
    best_metrics = evaluate_code(
        best_code,
        eval_seeds=args.eval_seeds,
        timeout=args.sandbox_timeout,
    )

    llm = LLMClient(settings=runtime.llm, dry_run=dry_run)
    hooks = build_default_hook_manager(run_dir, args)
    load_hook_specs(hooks, args.hook)
    attempts: list[dict[str, Any]] = []
    research_context = ""
    tokens_used = 0
    started_at = time.monotonic()

    print("Simple AutoResearch Agent Loop")
    print(f"  mode={'dry-run' if dry_run else 'live'}")
    print(f"  run_dir={run_dir}")
    print(f"  baseline={baseline_path}")
    print(f"  best={best_name} {_format_metric(best_metrics)}")
    print(f"  skills={len(skill_catalog_items)} from {skills_dir}")
    hooks.emit("run_start", {
        "mode": "dry-run" if dry_run else "live",
        "baseline": str(baseline_path),
        "best_name": best_name,
        "best_metrics": best_metrics,
        "args": vars(args),
        "skills": [s.catalog_line() for s in skill_catalog_items],
    })

    for round_no in range(1, args.max_rounds + 1):
        if args.max_seconds and time.monotonic() - started_at >= args.max_seconds:
            hooks.emit("termination", {
                "round": round_no,
                "reason": "max_seconds",
                "elapsed_seconds": time.monotonic() - started_at,
                "tokens_used": tokens_used,
            })
            print(f"  [stop] reached max_seconds={args.max_seconds}")
            break
        if args.max_tokens and tokens_used >= args.max_tokens:
            hooks.emit("termination", {
                "round": round_no,
                "reason": "max_tokens",
                "elapsed_seconds": time.monotonic() - started_at,
                "tokens_used": tokens_used,
            })
            print(f"  [stop] reached max_tokens={args.max_tokens}")
            break
        print(f"\n--- Round {round_no}/{args.max_rounds} ---")
        hooks.emit("round_start", {
            "round": round_no,
            "best_name": best_name,
            "best_metrics": best_metrics,
            "stalled_rounds": _stalled_rounds(attempts),
        })
        previous_best_name = best_name
        previous_best_metrics = dict(best_metrics)
        previous_best_code = best_code

        project_tool_context, project_tool_tokens = _run_project_tool_cycle(
            args=args,
            llm=llm,
            dry_run=dry_run,
            run_dir=run_dir,
            hooks=hooks,
            round_no=round_no,
            best_metrics=best_metrics,
            attempts=attempts,
        )
        tokens_used += project_tool_tokens
        if project_tool_context.strip():
            research_context = (research_context + "\n\n## Project tool evidence\n" + project_tool_context)[-24000:]

        if _should_research(args, attempts, round_no):
            call, research_tokens = _choose_research_call(
                llm=llm,
                dry_run=dry_run,
                best_metrics=best_metrics,
                attempts=attempts,
                research_context=research_context,
            )
            tokens_used += research_tokens
            hooks.emit("research_decision", {
                "round": round_no,
                "call": call,
                "decision": {
                    "action": "research" if call.get("tool") != "generate_solver" else "generate_solver",
                    "tool": call.get("tool"),
                    "purpose": call.get("reason", "选择下一步动作"),
                    "query": call.get("query"),
                    "url": call.get("url"),
                },
                "tokens_used": tokens_used,
            })
            result = _run_research_tool(call)
            append_research_markdown(run_dir, result)
            formatted = format_research_result(result)
            research_context = (research_context + "\n" + formatted)[-20000:]
            hooks.emit("tool_call", {
                "round": round_no,
                "tool": result.get("tool"),
                "query": result.get("query"),
                "url": result.get("url"),
                "reason": call.get("reason"),
                "purpose": "把外部/本地研究结果转化为下一轮 solver 改动线索",
                "error": result.get("error"),
                "summary_preview": (result.get("summary") or "")[:1000],
                "result_keys": sorted(str(k) for k in result.keys()),
            })
            if result.get("tool") != "generate_solver":
                print(f"  [research] {result.get('tool')} {result.get('query') or result.get('url') or ''}")

        skill_context = "\n".join([
            research_context,
            args.metric_hints or "",
            " ".join(str(a.get("reason", "")) for a in attempts[-5:]),
            " ".join(str(a.get("name", "")) for a in attempts[-5:]),
        ])
        selected_skills = [] if args.no_skills else select_skills(
            skill_catalog_items,
            text=skill_context,
            explicit_ids=args.skill,
            max_skills=args.max_skills,
        )
        selected_skill_text = format_selected_skills(selected_skills)
        hooks.emit("skill_selection", {
            "round": round_no,
            "selected": [s.id for s in selected_skills],
            "selected_details": [
                {
                    "id": s.id,
                    "name": s.name,
                    "description": s.description,
                    "triggers": s.triggers,
                }
                for s in selected_skills
            ],
            "available": [s.id for s in skill_catalog_items],
            "reason": "根据本轮研究上下文、metric hints、最近失败原因和显式 skill 参数选择可复用策略约束",
            "purpose": "把经验原则注入本轮 prompt，约束 solver 修改范围",
        })
        if selected_skills:
            print(f"  [skills] {', '.join(s.id for s in selected_skills)}")

        code, used = _generate_code(
            llm=llm,
            dry_run=dry_run,
            best_metrics=best_metrics,
            best_code=best_code,
            research_context=research_context,
            skill_catalog=skill_catalog_text,
            selected_skill_text=selected_skill_text,
            attempts=attempts,
            round_no=round_no,
            metric_hints=args.metric_hints,
        )
        tokens_used += used
        name = _strategy_name_from_code(code, f"round_{round_no}")
        code_summary = _code_header_summary(code)
        hooks.emit("generation", {
            "round": round_no,
            "name": name,
            "code_chars": len(code),
            "code_summary": code_summary,
            "purpose": "生成一个可独立提交的纯 Python solver 候选",
            "tokens_delta": used,
            "tokens_used": tokens_used,
        })
        if not code.strip():
            record = {
                "round": round_no,
                "name": name,
                "accepted": False,
                "reason": "LLM 无输出",
            }
            record["round_summary"] = _build_round_summary(
                record=record,
                previous_best_name=previous_best_name,
                previous_best_metrics=previous_best_metrics,
                current_best_name=best_name,
                current_best_metrics=best_metrics,
                llm_judge=None,
            )
            attempts.append(record)
            append_jsonl(run_dir, record)
            hooks.emit("round_summary", {
                "round": round_no,
                "name": name,
                "summary": record["round_summary"],
                "accepted": False,
                "reason": record["reason"],
                "tokens_used": tokens_used,
            })
            hooks.emit("round_end", record)
            print("  [skip] LLM 无输出")
            print(f"  [summary] {record['round_summary']}")
            continue

        candidate_path = run_dir / f"round_{round_no:03d}_{name}.py"
        candidate_path.write_text(code, encoding="utf-8")

        code, err, repair_tokens = _validate_and_maybe_repair(
            code=code,
            llm=llm,
            dry_run=dry_run,
            max_repair_attempts=args.max_repair_attempts,
        )
        tokens_used += repair_tokens
        name = _strategy_name_from_code(code, name)
        fixed_path = run_dir / f"round_{round_no:03d}_{name}_validated.py"
        fixed_path.write_text(code, encoding="utf-8")

        if err:
            record = {
                "round": round_no,
                "name": name,
                "accepted": False,
                "reason": err,
                "candidate_path": str(candidate_path),
                "validated_path": str(fixed_path),
                "tokens_used": tokens_used,
            }
            record["round_summary"] = _build_round_summary(
                record=record,
                previous_best_name=previous_best_name,
                previous_best_metrics=previous_best_metrics,
                current_best_name=best_name,
                current_best_metrics=best_metrics,
                llm_judge=None,
            )
            attempts.append(record)
            append_jsonl(run_dir, record)
            hooks.emit("validation", {
                "round": round_no,
                "name": name,
                "ok": False,
                "error": err,
                "candidate_path": str(candidate_path),
                "validated_path": str(fixed_path),
            })
            hooks.emit("round_summary", {
                "round": round_no,
                "name": name,
                "summary": record["round_summary"],
                "accepted": False,
                "reason": err,
                "tokens_used": tokens_used,
            })
            hooks.emit("round_end", record)
            print(f"  [reject-static] {err}")
            print(f"  [summary] {record['round_summary']}")
            continue
        hooks.emit("validation", {
            "round": round_no,
            "name": name,
            "ok": True,
            "candidate_path": str(candidate_path),
            "validated_path": str(fixed_path),
        })

        metrics = evaluate_code(code, eval_seeds=args.eval_seeds, timeout=args.sandbox_timeout)
        if not metrics.get("ok"):
            repaired_code, repaired_metrics, repair_eval_tokens = _repair_after_eval_failure(
                code=code,
                name=name,
                metrics=metrics,
                llm=llm,
                dry_run=dry_run,
                timeout=args.sandbox_timeout,
                eval_seeds=args.eval_seeds,
            )
            tokens_used += repair_eval_tokens
            if repaired_code != code:
                code = repaired_code
                name = _strategy_name_from_code(code, name)
                fixed_path = run_dir / f"round_{round_no:03d}_{name}_eval_repaired.py"
                fixed_path.write_text(code, encoding="utf-8")
                metrics = repaired_metrics
        accepted, reason = _accept(metrics, best_metrics, args.min_delta)
        metrics_text = _format_metric(metrics)
        hooks.emit("evaluation", {
            "round": round_no,
            "name": name,
            "metrics": metrics,
            "metrics_text": metrics_text,
        })
        judge_tokens = 0
        evaluator = evaluation_contract.get("evaluator") if isinstance(evaluation_contract, dict) else None
        wants_llm_judge = isinstance(evaluator, dict) and evaluator.get("type") == "llm_as_judge"
        if wants_llm_judge and args.max_tokens and tokens_used >= args.max_tokens:
            llm_judge = {
                "ok": False,
                "summary": f"已达到 max_tokens={args.max_tokens}，跳过 LLM-as-judge 补充评估。",
                "use_for_acceptance": False,
            }
        elif wants_llm_judge:
            llm_judge, judge_tokens = _run_llm_judge(
                llm=llm,
                dry_run=dry_run,
                contract=evaluation_contract,
                baseline_name=previous_best_name,
                baseline_code=previous_best_code,
                candidate_name=name,
                candidate_code=code,
                metrics=metrics,
                round_no=round_no,
            )
            tokens_used += judge_tokens
        else:
            llm_judge = None
        if llm_judge is not None:
            hooks.emit("llm_judge", {
                "round": round_no,
                "name": name,
                "judge": llm_judge,
                "tokens_delta": judge_tokens,
                "tokens_used": tokens_used,
                "purpose": "使用同一个 LLM API 对候选方案做语义评估补充，不直接替代本地确定性评测",
            })
        print(f"  {name}: {metrics_text}")
        print(f"  accepted={accepted} reason={reason}")

        snapshot_py = None
        if accepted:
            sid = name.replace(" ", "_").replace("/", "_").lower()
            add_strategy(
                sid=sid,
                name=name,
                stype="simple_loop",
                code=code,
                tags=["simple_loop", "llm_generated" if not dry_run else "dry_run"],
                rationale=reason,
            )
            update_performance(
                sid,
                float(metrics["min_det_cov"]),
                float(metrics["avg_det_score"]),
                0.0,
                0.0,
                args.eval_seeds,
            )
            snapshot_py = archive_solver_snapshot(name, code, metadata={
                "source": "simple_loop",
                "reason": reason,
                "metrics": {
                    "avg_det_score": metrics["avg_det_score"],
                    "min_det_cov": metrics["min_det_cov"],
                    "avg_time_ms": metrics["avg_time_ms"],
                },
            })
            best_code = code
            best_name = name
            best_metrics = metrics
            if args.export_best:
                (REPO_ROOT / "solver.py").write_text(code, encoding="utf-8")
                print("  [export] solver.py 已被新 best 覆盖")
            hooks.emit("accepted", {
                "round": round_no,
                "name": name,
                "reason": reason,
                "snapshot_py": snapshot_py,
                "exported": bool(args.export_best),
            })

        record = {
            "round": round_no,
            "name": name,
            "accepted": accepted,
            "reason": reason,
            "metrics": metrics,
            "metrics_text": metrics_text,
            "llm_judge": llm_judge,
            "candidate_path": str(candidate_path),
            "validated_path": str(fixed_path),
            "snapshot_py": snapshot_py,
            "tokens_used": tokens_used,
        }
        record["round_summary"] = _build_round_summary(
            record=record,
            previous_best_name=previous_best_name,
            previous_best_metrics=previous_best_metrics,
            current_best_name=best_name,
            current_best_metrics=best_metrics,
            llm_judge=llm_judge,
        )
        attempts.append(record)
        append_jsonl(run_dir, record)
        hooks.emit("round_summary", {
            "round": round_no,
            "name": name,
            "summary": record["round_summary"],
            "accepted": accepted,
            "reason": reason,
            "tokens_used": tokens_used,
        })
        hooks.emit("round_end", record)
        print(f"  [summary] {record['round_summary']}")

        skill_tokens = _maybe_write_new_skill(
            args=args,
            llm=llm,
            dry_run=dry_run,
            skills_dir=skills_dir,
            skill_catalog_items=skill_catalog_items,
            attempts=attempts,
            research_context=research_context,
            hooks=hooks,
            round_no=round_no,
        )
        if skill_tokens:
            tokens_used += skill_tokens
            skill_catalog_items = [] if args.no_skills else discover_skills(skills_dir)
            skill_catalog_text = format_skill_catalog(skill_catalog_items)

    summary = {
        "best_name": best_name,
        "best_metrics": best_metrics,
        "tokens_used": tokens_used,
        "elapsed_seconds": time.monotonic() - started_at,
        "attempts": len(attempts),
        "run_dir": str(run_dir),
    }
    (run_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print("\n=== Done ===")
    print(f"  best={best_name} {_format_metric(best_metrics)}")
    print(f"  run_dir={run_dir}")
    hooks.emit("run_end", summary)
    return summary


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="简单 AutoResearch Agent loop（无 LangGraph）。")
    p.add_argument("--live", action="store_true", help="调用 LLM；默认 dry-run")
    p.add_argument("--max-rounds", type=int, default=5, help="最大迭代轮数")
    p.add_argument("--max-seconds", type=float, default=0.0, help="最大运行秒数；0 表示不限制")
    p.add_argument("--max-tokens", type=int, default=0, help="最大 LLM token 用量；0 表示不限制")
    p.add_argument("--eval-seeds", type=int, default=1, help="每个校准 preset 的 seed 数")
    p.add_argument("--sandbox-timeout", type=float, default=5.0, help="单数据集运行超时秒数")
    p.add_argument("--max-repair-attempts", type=int, default=2, help="LLM 修复尝试次数")
    p.add_argument("--min-delta", type=float, default=1.0, help="平均 DetScore 至少改善多少才采纳")
    p.add_argument("--baseline", default="solver.py", help="当前 best/baseline solver 路径")
    p.add_argument("--export-best", action="store_true", help="采纳新 best 后覆盖根目录 solver.py")
    p.add_argument("--run-dir", default=None, help="指定 runs/<id> 目录")
    p.add_argument("--settings", default=None, help="LLM JSON 配置路径")
    p.add_argument("--evaluation-contract", default=None, help="本次运行的 Evaluation Contract JSON 路径")
    p.add_argument("--metric-hints", default=None, help="额外指标提示，写入 LLM prompt")
    p.add_argument("--no-research", action="store_true", help="禁用研究工具")
    p.add_argument("--initial-research", action="store_true", help="第 1 轮生成前先做一次研究")
    p.add_argument("--research-on-stall", type=int, default=3, help="连续多少轮未采纳后触发研究；0 表示禁用")
    p.add_argument("--research-every", type=int, default=0, help="固定每 N 轮研究一次；0 表示禁用")
    p.add_argument("--enable-project-tools", action="store_true", help="允许每轮生成前使用项目内受限工具")
    p.add_argument("--project-tool-steps", type=int, default=6, help="live 模式每轮最多执行多少个项目工具动作")
    p.add_argument("--project-tool-warmup", action="store_true", help="live 模式也先执行一次固定项目回放工具序列")
    p.add_argument("--hook", action="append", default=[], help="注册自定义 Hook，格式 module:function，可重复")
    p.add_argument("--skills-dir", default="agent/skills", help="Skill Markdown 目录")
    p.add_argument("--skill", action="append", default=[], help="显式加载某个 skill id，可重复")
    p.add_argument("--max-skills", type=int, default=4, help="每轮最多加载几个 skill 正文")
    p.add_argument("--no-skills", action="store_true", help="禁用 skill 动态加载")
    p.add_argument("--list-skills", action="store_true", help="列出预加载 skill 描述后退出")
    p.add_argument("--allow-skill-write", action="store_true", help="允许 Agent 在连续失败后写入新 skill")
    p.add_argument("--skill-write-on-stall", type=int, default=4, help="连续失败多少轮后尝试写 skill")
    p.add_argument("--llm-api-key", default=None, help="覆盖配置文件 api_key")
    p.add_argument("--llm-base-url", default=None, help="覆盖配置文件 base_url")
    p.add_argument("--llm-model", default=None, help="覆盖配置文件 model")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    run_loop(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
