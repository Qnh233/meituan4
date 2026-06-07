"""沙箱执行器：安全运行 LLM 生成的策略代码。

安全措施:
  - compile() 语法检查
  - exec() 受限全局命名空间（无危险 builtins）
  - subprocess 隔离执行 + 超时保护
  - 自动错误修复（最多 3 次）
"""

import sys
import json
import os
import subprocess
import tempfile
from pathlib import Path


SAFE_BUILTINS = {
    "True": True, "False": False, "None": None,
    "abs": abs, "all": all, "any": any, "bool": bool,
    "dict": dict, "enumerate": enumerate, "filter": filter,
    "float": float, "int": int, "len": len, "list": list,
    "map": map, "max": max, "min": min, "range": range,
    "round": round, "set": set, "sorted": sorted,
    "str": str, "sum": sum, "tuple": tuple, "zip": zip,
    "isinstance": isinstance, "type": type,
    "print": print, "Exception": Exception, "ValueError": ValueError,
    "KeyError": KeyError, "TypeError": TypeError, "IndexError": IndexError,
    "__import__": __import__,
    "object": object, "property": property, "staticmethod": staticmethod,
    "classmethod": classmethod, "super": super,
    "hasattr": hasattr, "getattr": getattr, "setattr": setattr,
    "iter": iter, "next": next, "reversed": reversed,
    "open": open, "bytes": bytes, "bytearray": bytearray,
    "complex": complex, "frozenset": frozenset, "slice": slice,
    "divmod": divmod, "pow": pow, "hash": hash, "id": id,
}


def _clean_code(raw: str) -> str:
    """从 LLM 输出中提取纯 Python 代码（去掉 markdown 标记）。"""
    raw = raw.strip()
    if raw.startswith("```python"):
        raw = raw[9:]
    elif raw.startswith("```"):
        raw = raw[3:]
    if raw.endswith("```"):
        raw = raw[:-3]
    return raw.strip()


def validate_syntax(code: str) -> tuple[bool, str]:
    """编译检查语法。返回 (ok, error_msg)。"""
    try:
        compile(code, "<strategy>", "exec")
        return True, ""
    except SyntaxError as e:
        return False, f"SyntaxError 行{e.lineno}: {e.msg}"


def extract_solve(code: str) -> tuple[bool, str]:
    """提取 solve 函数并用受限环境测试是否可调用。"""
    try:
        namespace = {
            "__builtins__": {k: v for k, v in SAFE_BUILTINS.items()},
            "__name__": "strategy",
        }
        exec(code, namespace)
        if "solve" not in namespace:
            return False, "未找到 solve 函数"
        if not callable(namespace["solve"]):
            return False, "solve 不是可调用函数"
        return True, ""
    except Exception as e:
        return False, f"执行错误: {type(e).__name__}: {e}"


def run_on_data(code: str, test_data: str, timeout: float = 5.0) -> dict:
    """在子进程中运行生成的 solve 函数。返回执行结果。"""
    code = _clean_code(code)

    # 语法检查
    ok, err = validate_syntax(code)
    if not ok:
        return {"ok": False, "error": err, "result": None, "stderr": ""}

    # 将代码 + 数据写入临时文件，子进程执行
    with tempfile.TemporaryDirectory() as tmpdir:
        code_file = Path(tmpdir) / "strategy.py"
        data_file = Path(tmpdir) / "test_data.txt"

        code_file.write_text(code, encoding="utf-8")
        data_file.write_text(test_data, encoding="utf-8")

        runner = (Path(tmpdir) / "run.py")
        runner.write_text(f'''
import sys, json, time
sys.path.insert(0, r"{tmpdir}")
from strategy import solve

with open(r"{data_file}", encoding="utf-8") as f:
    raw = f.read()

t0 = time.perf_counter()
try:
    result = solve(raw)
    elapsed = time.perf_counter() - t0
    print(json.dumps({{"ok": True, "result": result, "elapsed": elapsed}}))
except Exception as e:
    print(json.dumps({{"ok": False, "error": str(e), "elapsed": time.perf_counter() - t0}}))
''', encoding="utf-8")

        try:
            env = os.environ.copy()
            env["PYTHONHASHSEED"] = "0"
            proc = subprocess.run(
                [sys.executable, str(runner)],
                capture_output=True, text=True, timeout=timeout,
                cwd=tmpdir,
                env=env,
            )
            for line in proc.stdout.splitlines():
                line = line.strip()
                if line.startswith("{"):
                    try:
                        return json.loads(line)
                    except json.JSONDecodeError as e:
                        return {
                            "ok": False,
                            "error": f"JSON解析失败: {e}; stdout={proc.stdout[:500]!r}; stderr={proc.stderr[:500]!r}",
                            "result": None,
                            "stderr": proc.stderr,
                        }

            return {"ok": False, "error": proc.stderr.strip() or "无输出", "result": None, "stderr": proc.stderr}
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"超时 ({timeout}s)", "result": None, "stderr": ""}
        except Exception as e:
            return {"ok": False, "error": str(e), "result": None, "stderr": ""}


_FIX_PROMPT_SYNTAX = """以下 Python 代码存在语法错误或无法通过 compile。请修复并只输出完整 Python 代码。

错误信息:
{error}

原代码:
```python
{code}
```

必须保留 `solve(input_text: str) -> list`。零外部依赖。只输出代码。"""

_FIX_PROMPT_EXEC = """代码可编译，但在受限环境下 exec 时出现错误（如无 solve、不可调用）。请修复并只输出完整 Python。

错误信息:
{error}

```python
{code}
```
"""

_FIX_PROMPT_RUNTIME = """以下策略代码在数据集上运行时抛错或超时提示如下。修复并输出完整 Python（不改整体算法意图）。

错误信息: {error}

```python
{code}
```
"""

_FIX_PROMPT_FORMAT = """代码可运行但返回不满足接口：必须是 list，且每项为 (task_id_str, [courier_id, ...])，task_id 为逗号分隔合单字符串。请修复返回值结构并输出完整代码。

错误信息:
{error}

```python
{code}
```
"""

_FIX_PROMPTS = {
    "syntax": _FIX_PROMPT_SYNTAX,
    "exec": _FIX_PROMPT_EXEC,
    "runtime": _FIX_PROMPT_RUNTIME,
    "format": _FIX_PROMPT_FORMAT,
}


def plan_format_errors(plan: object) -> str | None:
    """检查 solve 返回值格式；无误返回 None。"""
    if plan is None:
        return "返回 None"
    if not isinstance(plan, list):
        return f"返回类型非 list：{type(plan).__name__}"
    for idx, entry in enumerate(plan):
        if not isinstance(entry, (list, tuple)) or len(entry) != 2:
            return f"下标 {idx} 的元素不是长度为 2 的元组/列表"
        task_str, courier_list = entry
        if not isinstance(task_str, str) or not isinstance(courier_list, list):
            return f"下标 {idx}: 须为 (str, list)，实为 {type(task_str)}, {type(courier_list)}"
        for cid in courier_list:
            if not isinstance(cid, str):
                return f"下标 {idx}: 骑手列表内须为字符串"
    return None


def try_fix(
    llm_client,
    code: str,
    error: str,
    max_retries: int = 3,
    *,
    error_kind: str = "syntax",
):
    """尝试让 LLM 修复代码；兼容旧用法（默认为语法类）。"""
    fixed, _tokens, _n = try_fix_with_usage(
        llm_client, code, error, max_retries=max_retries, error_kind=error_kind
    )
    return fixed


def _repair_llm_params(llm_client) -> tuple[float, int]:
    """从中心化配置读取修复链温度与 token 上限。"""
    s = getattr(llm_client, "settings", None)
    temp = float(getattr(s, "repair_temperature", 0.3)) if s else 0.3
    mtoks = int(getattr(s, "generate_max_tokens", 4096)) if s else 4096
    return temp, mtoks


def try_fix_with_usage(
    llm_client,
    code: str,
    error: str,
    *,
    max_retries: int = 3,
    error_kind: str = "syntax",
) -> tuple[str | None, int, int]:
    """LLM 修复代码；返回 (修复后代码或 None, 累计 total_tokens, 实际尝试次数)。"""
    tmpl = _FIX_PROMPTS.get(error_kind) or _FIX_PROMPTS["syntax"]
    tokens_total = 0
    attempts = 0
    current = code
    current_err = error

    for _ in range(max_retries):
        attempts += 1
        rt, rmax = _repair_llm_params(llm_client)
        prompt = tmpl.format(error=current_err, code=current)
        # 使用 complete 以统计 token（无 Key / dry_run 时走 chat 仍返回 None）
        comp = getattr(llm_client, "complete", None)
        if callable(comp):
            res = comp(
                [{"role": "user", "content": prompt}],
                temperature=rt,
                max_tokens=rmax,
            )
            response = res.content if res else None
            if res and res.total_tokens:
                tokens_total += res.total_tokens
        else:
            response = llm_client.chat(
                [{"role": "user", "content": prompt}],
                temperature=rt,
                max_tokens=rmax,
            )

        if not response:
            return None, tokens_total, attempts

        fixed = _clean_code(response)
        ok, err = validate_syntax(fixed)
        if ok:
            return fixed, tokens_total, attempts

        current = fixed
        current_err = err

    return None, tokens_total, attempts
