"""Hook 示例。

运行示例：
    python search.py --max-rounds 1 --hook agent.sample_hooks:register_hooks
"""

from __future__ import annotations

import json


def _accepted_brief(event_type, payload, context) -> None:
    """采纳策略时追加一份简短摘要，便于可视化或人工快速查看。"""

    path = context.run_dir / "accepted.md"
    line = (
        f"- round={payload.get('round')} name={payload.get('name')} "
        f"reason={payload.get('reason')} snapshot={payload.get('snapshot_py')}\n"
    )
    with open(path, "a", encoding="utf-8") as f:
        f.write(line)


def _metrics_json(event_type, payload, context) -> None:
    """把每轮评测指标单独落一行，方便图表工具直接读取。"""

    metrics = payload.get("metrics") or {}
    record = {
        "round": payload.get("round"),
        "name": payload.get("name"),
        "ok": metrics.get("ok"),
        "avg_det_score": metrics.get("avg_det_score"),
        "min_det_cov": metrics.get("min_det_cov"),
        "avg_time_ms": metrics.get("avg_time_ms"),
    }
    with open(context.run_dir / "metrics.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def register_hooks(manager) -> None:
    manager.register("accepted", _accepted_brief)
    manager.register("evaluation", _metrics_json)
