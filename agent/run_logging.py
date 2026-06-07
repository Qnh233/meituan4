"""每次离线 run 可追溯产物：runs/<run_id>/iterations.jsonl。"""

from __future__ import annotations

import json
import random
import string
import time
from pathlib import Path

RUNS_PARENT = Path(__file__).resolve().parent.parent / "runs"


def new_run_id() -> str:
    """时间戳 + 短后缀，便于目录排序与人工辨认。"""
    ts = time.strftime("%Y%m%d_%H%M%S")
    suf = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"{ts}_{suf}"


def ensure_run_directory(run_id: str) -> Path:
    """创建 runs/<run_id>/。"""
    p = RUNS_PARENT / run_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def iterations_jsonl_path(run_dir: Path) -> Path:
    return run_dir / "iterations.jsonl"


def events_jsonl_path(run_dir: Path) -> Path:
    return run_dir / "events.jsonl"


def reflection_md_path(run_dir: Path) -> Path:
    return run_dir / "reflection.md"


def append_jsonl(run_dir: Path, record: dict) -> None:
    """追加一行迭代记录（原子性要求不高，单行 json）。"""
    path = iterations_jsonl_path(run_dir)
    line = json.dumps(record, ensure_ascii=False, default=str) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line)


def append_event(run_dir: Path, event_type: str, payload: dict | None = None) -> None:
    """追加全链路事件日志，供后续可视化消费。"""
    record = {
        "time_local": time.strftime("%Y-%m-%d %H:%M:%S"),
        "event_type": event_type,
        "payload": payload or {},
    }
    path = events_jsonl_path(run_dir)
    line = json.dumps(record, ensure_ascii=False, default=str) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line)


def append_reflection_md(run_dir: Path, markdown_chunk: str) -> None:
    """可选：在每轮 Reflect 后将摘要追加写入。"""
    p = reflection_md_path(run_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        if not markdown_chunk.endswith("\n"):
            markdown_chunk += "\n"
        f.write(markdown_chunk)
