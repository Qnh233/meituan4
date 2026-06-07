"""Project-scoped tools for the AutoResearch loop.

These tools deliberately keep every file operation inside the repository root.
They are meant for offline agent analysis: inspect files, summarize online
evaluation history, write replay/analysis Python scripts under the run
directory, and execute those scripts without shell interpolation.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class ToolResult:
    ok: bool
    tool: str
    reason: str
    purpose: str
    params: dict[str, Any]
    summary: str
    artifacts: list[str]
    error: str = ""

    def as_event_payload(self, round_no: int) -> dict[str, Any]:
        return {
            "round": round_no,
            "tool": self.tool,
            "reason": self.reason,
            "purpose": self.purpose,
            "params": self.params,
            "summary_preview": self.summary[:4000],
            "artifacts": self.artifacts,
            "error": self.error or None,
            "result_keys": ["summary", "artifacts", "error", "params"],
        }

    def format_for_prompt(self) -> str:
        status = "ok" if self.ok else "error"
        lines = [
            f"### Tool: {self.tool} ({status})",
            f"Reason: {self.reason}",
            f"Purpose: {self.purpose}",
            f"Params: {json.dumps(self.params, ensure_ascii=False)}",
        ]
        if self.error:
            lines.append(f"Error: {self.error}")
        if self.artifacts:
            lines.append("Artifacts: " + ", ".join(self.artifacts))
        lines += ["Result:", self.summary.strip()]
        return "\n".join(lines)


class ProjectToolExecutor:
    """Execute a narrow set of project-local tools.

    Path policy:
    - repo_root is the only readable/writable tree.
    - analysis scripts are written under run_dir/tool_scripts by default.
    - commands are never passed through a shell.
    """

    def __init__(self, repo_root: Path, run_dir: Path):
        self.repo_root = repo_root.resolve()
        self.run_dir = self._safe_path(run_dir)
        self.scripts_dir = self.run_dir / "tool_scripts"
        self.scripts_dir.mkdir(parents=True, exist_ok=True)

    def _safe_path(self, path: str | Path) -> Path:
        raw = Path(path)
        resolved = raw.resolve() if raw.is_absolute() else (self.repo_root / raw).resolve()
        try:
            resolved.relative_to(self.repo_root)
        except ValueError as exc:
            raise ValueError(f"path outside project root: {path}") from exc
        return resolved

    def _relative(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(self.repo_root)).replace("\\", "/")
        except ValueError:
            return str(path)

    def list_files(self, pattern: str = "*.py", limit: int = 80, reason: str = "", purpose: str = "") -> ToolResult:
        try:
            files = []
            for path in self.repo_root.glob(pattern):
                if "__pycache__" in path.parts or ".git" in path.parts or "node_modules" in path.parts:
                    continue
                if path.is_file():
                    files.append(self._relative(path))
                if len(files) >= max(1, min(limit, 300)):
                    break
            return ToolResult(True, "list_files", reason, purpose, {"pattern": pattern, "limit": limit}, "\n".join(files), [])
        except Exception as exc:
            return ToolResult(False, "list_files", reason, purpose, {"pattern": pattern, "limit": limit}, "", [], f"{type(exc).__name__}: {exc}")

    def read_file(self, path: str, max_chars: int = 12000, reason: str = "", purpose: str = "") -> ToolResult:
        params = {"path": path, "max_chars": max_chars}
        try:
            resolved = self._safe_path(path)
            text = resolved.read_text(encoding="utf-8", errors="replace")
            truncated = text[: max(100, min(max_chars, 50000))]
            if len(text) > len(truncated):
                truncated += "\n...[truncated]"
            return ToolResult(True, "read_file", reason, purpose, params, truncated, [self._relative(resolved)])
        except Exception as exc:
            return ToolResult(False, "read_file", reason, purpose, params, "", [], f"{type(exc).__name__}: {exc}")

    def analyze_online_results(self, limit: int = 8, reason: str = "", purpose: str = "") -> ToolResult:
        params = {"limit": limit}
        try:
            eval_dir = self.repo_root / "evaluations"
            files = sorted(eval_dir.glob("online_result_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[: max(1, min(limit, 30))]
            rows: list[dict[str, Any]] = []
            for path in files:
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                cases = data.get("case_results") or []
                rows.append({
                    "file": self._relative(path),
                    "avg_score": data.get("avg_score"),
                    "success": f"{data.get('success_count')}/{data.get('case_count')}",
                    "cases": [
                        {
                            "case": c.get("case_file"),
                            "score": c.get("total_score"),
                            "assigned": c.get("assigned_count"),
                            "unassigned": c.get("unassigned_count"),
                            "multi": sum(1 for d in (c.get("detail") or []) if len(d.get("couriers") or []) > 1),
                            "bundles": sum(1 for d in (c.get("detail") or []) if "," in str(d.get("task_id_list") or "")),
                        }
                        for c in cases
                    ],
                })
            summary = json.dumps(rows, ensure_ascii=False, indent=2)[:20000]
            return ToolResult(True, "analyze_online_results", reason, purpose, params, summary, [r["file"] for r in rows])
        except Exception as exc:
            return ToolResult(False, "analyze_online_results", reason, purpose, params, "", [], f"{type(exc).__name__}: {exc}")

    def write_analysis_script(self, filename: str, code: str, reason: str = "", purpose: str = "") -> ToolResult:
        safe_name = Path(filename).name
        if not safe_name.endswith(".py"):
            safe_name += ".py"
        params = {"filename": safe_name, "chars": len(code)}
        try:
            target = (self.scripts_dir / safe_name).resolve()
            target.relative_to(self.repo_root)
            header = (
                "# Auto-generated project-local analysis script.\n"
                "# It must run inside the repository and should not access paths outside it.\n\n"
            )
            target.write_text(header + code.strip() + "\n", encoding="utf-8")
            return ToolResult(True, "write_analysis_script", reason, purpose, params, f"wrote {self._relative(target)}", [self._relative(target)])
        except Exception as exc:
            return ToolResult(False, "write_analysis_script", reason, purpose, params, "", [], f"{type(exc).__name__}: {exc}")

    def run_python(self, path: str, args: list[str] | None = None, timeout: float = 30.0, reason: str = "", purpose: str = "") -> ToolResult:
        args = [str(a) for a in (args or [])]
        params = {"path": path, "args": args, "timeout": timeout}
        try:
            script = self._safe_path(path)
            if script.suffix.lower() != ".py":
                raise ValueError("only .py scripts can be executed")
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            proc = subprocess.run(
                [sys.executable, str(script), *args],
                cwd=self.repo_root,
                env=env,
                capture_output=True,
                text=True,
                timeout=max(1.0, min(float(timeout), 120.0)),
            )
            output = []
            if proc.stdout:
                output.append("STDOUT:\n" + proc.stdout[-12000:])
            if proc.stderr:
                output.append("STDERR:\n" + proc.stderr[-6000:])
            ok = proc.returncode == 0
            return ToolResult(ok, "run_python", reason, purpose, params, "\n\n".join(output) or f"exit={proc.returncode}", [self._relative(script)], "" if ok else f"exit code {proc.returncode}")
        except Exception as exc:
            return ToolResult(False, "run_python", reason, purpose, params, "", [], f"{type(exc).__name__}: {exc}")


def default_replay_script() -> str:
    """A compact script that replays the recent solver-iteration evidence."""

    return r'''
from __future__ import annotations

import json
from pathlib import Path

root = Path.cwd()
files = sorted((root / "evaluations").glob("online_result_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:8]
print(f"recent_online_results={len(files)}")
previous = None
for path in reversed(files):
    data = json.loads(path.read_text(encoding="utf-8"))
    avg = float(data.get("avg_score") or 0.0)
    delta = "" if previous is None else f" delta={avg - previous:+.2f}"
    print(f"\n{path.name}: avg={avg:.2f}{delta} success={data.get('success_count')}/{data.get('case_count')}")
    previous = avg
    for case in data.get("case_results", []):
        details = case.get("detail") or []
        multi = sum(1 for d in details if len(d.get("couriers") or []) > 1)
        bundles = sum(1 for d in details if "," in str(d.get("task_id_list") or ""))
        print(
            f"  {case.get('case_file')}: score={float(case.get('total_score') or 0.0):.2f} "
            f"assigned={case.get('assigned_count')} unassigned={case.get('unassigned_count')} "
            f"multi={multi} bundles={bundles}"
        )
'''.strip()


def run_default_project_tool_sequence(executor: ProjectToolExecutor, round_no: int) -> list[ToolResult]:
    """Deterministic tool sequence used in dry-run and as a first live warm-up."""

    results = [
        executor.analyze_online_results(
            limit=6,
            reason="replay the exact online evidence from recent solver iterations",
            purpose="extract which scenario improved or regressed before proposing the next solver direction",
        ),
        executor.read_file(
            "solver.py",
            max_chars=16000,
            reason="inspect the current best solver implementation",
            purpose="ground the next edit in the real code instead of relying on memory",
        ),
        executor.write_analysis_script(
            f"round_{round_no:03d}_replay_online_results.py",
            default_replay_script(),
            reason="create a reusable replay script for this iteration process",
            purpose="make score movement, multi-courier usage, and bundle usage visible to the agent and UI",
        ),
    ]
    script_artifact = results[-1].artifacts[0] if results[-1].artifacts else ""
    if script_artifact:
        results.append(executor.run_python(
            script_artifact,
            timeout=20,
            reason="execute the replay script just written",
            purpose="verify the script works and feed its summary back into the next decision",
        ))
    return results
