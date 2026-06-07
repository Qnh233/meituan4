"""策略库持久化存储。

存储结构：
  library/
    strategies.json      # 元数据索引
    codes/               # LLM 生成策略的源代码
    performance/         # 各策略的评测记录
  snapshots/             # solver.py 版本快照

策略元数据格式：
  {
    "id": "greedy_score_v1",
    "name": "GreedyScore",
    "type": "handcrafted",       # handcrafted | llm_generated
    "module_path": "...",
    "code_path": null,
    "rationale": "按 total_score 升序贪心，试探纯成本优先策略的下界",
    "performance": {
      "deterministic": {"coverage": 1.0, "score": 424.5},
      "monte_carlo": {"coverage": 0.532, "score": 226.3, "n_sims": 100}
    },
    "performance_history": [
      {"det_cov": 1.0, "det_score": 430.0, "mc_cov": 0.54, "mc_score": 230.0, "date": "2026-05-13"}
    ],
    "tags": ["greedy", "fast"],
    "created_at": "2026-05-13"
  }
"""

import json
import os
import time
from pathlib import Path

LIBRARY_DIR = Path(__file__).parent
STRATEGIES_FILE = LIBRARY_DIR / "strategies.json"
CODES_DIR = LIBRARY_DIR / "codes"
PERFORMANCE_DIR = LIBRARY_DIR / "performance"


def ensure_dirs():
    CODES_DIR.mkdir(exist_ok=True)
    PERFORMANCE_DIR.mkdir(exist_ok=True)


def load_library() -> dict:
    """加载策略库索引。"""
    if not STRATEGIES_FILE.exists():
        return {"strategies": []}
    with open(STRATEGIES_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_library(lib: dict):
    ensure_dirs()
    with open(STRATEGIES_FILE, "w", encoding="utf-8") as f:
        json.dump(lib, f, ensure_ascii=False, indent=2)


def add_strategy(*, sid: str, name: str, stype: str, module_path: str | None = None,
                 code: str | None = None, tags: list[str] | None = None,
                 rationale: str = ""):
    """添加一条策略记录。"""
    lib = load_library()
    # 检查重复：更新 rationale 和时间戳
    for s in lib["strategies"]:
        if s["id"] == sid:
            s["updated_at"] = time.strftime("%Y-%m-%d %H:%M")
            if rationale and not s.get("rationale"):
                s["rationale"] = rationale
            save_library(lib)
            return

    entry = {
        "id": sid,
        "name": name,
        "type": stype,
        "module_path": module_path,
        "code_path": None,
        "rationale": rationale,
        "performance": {},
        "performance_history": [],
        "tags": tags or [],
        "created_at": time.strftime("%Y-%m-%d %H:%M"),
    }

    if code:
        ensure_dirs()
        code_file = CODES_DIR / f"{sid}.py"
        with open(code_file, "w", encoding="utf-8") as f:
            f.write(code)
        entry["code_path"] = str(code_file)

    lib["strategies"].append(entry)
    save_library(lib)


def update_performance(sid: str, det_cov: float, det_score: float,
                       mc_cov: float, mc_score: float, n_sims: int = 100):
    """更新策略的评测表现，追加历史记录。"""
    lib = load_library()
    for s in lib["strategies"]:
        if s["id"] == sid:
            old_perf = s.get("performance", {})
            s["performance"] = {
                "deterministic": {"coverage": det_cov, "score": det_score},
                "monte_carlo": {"coverage": mc_cov, "score": mc_score, "n_sims": n_sims},
            }
            # 追加历史（仅当数据有变化时）
            history = s.get("performance_history", [])
            old_mc = old_perf.get("monte_carlo", {})
            if not history or abs(old_mc.get("coverage", -1) - mc_cov) > 0.001 or abs(old_mc.get("score", -1) - mc_score) > 0.1:
                history.append({
                    "det_cov": det_cov,
                    "det_score": det_score,
                    "mc_cov": mc_cov,
                    "mc_score": mc_score,
                    "date": time.strftime("%Y-%m-%d %H:%M"),
                })
                # 只保留最近 20 条
                s["performance_history"] = history[-20:]
            save_library(lib)
            return
    # 不存在则新建
    add_strategy(sid=sid, name=sid, stype="unknown")
    update_performance(sid, det_cov, det_score, mc_cov, mc_score, n_sims)


def get_top_strategies(top_k: int = 5) -> list[dict]:
    """返回 MC 覆盖率最高的 top_k 个策略。"""
    lib = load_library()
    with_mc = [
        s for s in lib["strategies"]
        if s.get("performance", {}).get("monte_carlo", {}).get("coverage") is not None
    ]
    with_mc.sort(
        key=lambda s: s["performance"]["monte_carlo"]["coverage"],
        reverse=True,
    )
    return with_mc[:top_k]


def list_code_files() -> list[str]:
    """列出所有 LLM 生成的代码文件。"""
    ensure_dirs()
    return sorted(str(p) for p in CODES_DIR.glob("*.py"))


SNAPSHOTS_DIR = LIBRARY_DIR.parent / "snapshots"


def archive_solver_snapshot(strategy_name: str, code: str, *, metadata: dict | None = None):
    """保存 solver.py 版本快照，不覆盖历史。

    文件命名: solver_{strategy_name}_{timestamp}.py
    同时保存同名的 .json 元数据文件。
    """
    SNAPSHOTS_DIR.mkdir(exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    safe_name = strategy_name.replace(" ", "_").replace("/", "_").lower()
    stem = f"solver_{safe_name}_{ts}"

    code_file = SNAPSHOTS_DIR / f"{stem}.py"
    with open(code_file, "w", encoding="utf-8") as f:
        f.write(code)

    if metadata:
        meta_file = SNAPSHOTS_DIR / f"{stem}.json"
        metadata["strategy_name"] = strategy_name
        metadata["timestamp"] = ts
        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)

    return str(code_file)


def list_snapshots() -> list[dict]:
    """列出所有 solver 快照。"""
    if not SNAPSHOTS_DIR.exists():
        return []
    snapshots = []
    for py_file in sorted(SNAPSHOTS_DIR.glob("solver_*.py"), reverse=True):
        stem = py_file.stem
        meta_file = SNAPSHOTS_DIR / f"{stem}.json"
        meta = {}
        if meta_file.exists():
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        snapshots.append({
            "file": str(py_file),
            "name": stem,
            "size": py_file.stat().st_size,
            "metadata": meta,
        })
    return snapshots
