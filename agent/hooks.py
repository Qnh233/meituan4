"""Simple loop 生命周期 Hook 系统。

Hook 是轻量扩展点，不改变主 loop 的顺序控制流。默认 Hook 会把所有事件写入
`runs/<id>/events.jsonl`；用户可通过 `--hook module:function` 注册额外 Hook。

Hook 函数签名：
    hook_fn(event_type: str, payload: dict, context: HookContext) -> None

如果函数名是 `register_hooks(manager)`，则可在函数内部批量注册多个事件。
"""

from __future__ import annotations

import importlib
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from agent.run_logging import append_event


HookFn = Callable[[str, dict[str, Any], "HookContext"], None]


@dataclass
class HookContext:
    """传给 Hook 的运行上下文。"""

    run_dir: Path
    args: Any
    state: dict[str, Any] = field(default_factory=dict)


class HookManager:
    """按事件名管理 Hook。事件名 `*` 表示监听所有事件。"""

    def __init__(self, context: HookContext):
        self.context = context
        self._hooks: dict[str, list[HookFn]] = {}

    def register(self, event_type: str, fn: HookFn) -> None:
        event_type = event_type or "*"
        self._hooks.setdefault(event_type, []).append(fn)

    def emit(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        payload = payload or {}
        self.context.state["last_event_type"] = event_type
        self.context.state["last_event_at"] = time.strftime("%Y-%m-%d %H:%M:%S")

        for fn in self._hooks.get("*", []):
            fn(event_type, payload, self.context)
        for fn in self._hooks.get(event_type, []):
            fn(event_type, payload, self.context)


def hook(event_type: str) -> Callable[[HookFn], HookFn]:
    """声明 Hook 监听的事件，供动态加载时自动注册。"""

    def _wrap(fn: HookFn) -> HookFn:
        setattr(fn, "_agent_hook_event", event_type)
        return fn

    return _wrap


def event_log_hook(event_type: str, payload: dict[str, Any], context: HookContext) -> None:
    """默认 Hook：所有事件落 `events.jsonl`。"""

    append_event(context.run_dir, event_type, payload)


def build_default_hook_manager(run_dir: Path, args: Any) -> HookManager:
    manager = HookManager(HookContext(run_dir=run_dir, args=args))
    manager.register("*", event_log_hook)
    return manager


def load_hook_spec(manager: HookManager, spec: str) -> None:
    """加载 `module:function` Hook 规格。

    支持两种形式：
    - `pkg.mod:register_hooks`：函数接收 manager，自行注册多个 Hook。
    - `pkg.mod:my_hook`：函数按 HookFn 签名执行；事件来自 `@hook`，默认 `*`。
    """

    if ":" not in spec:
        raise ValueError(f"Hook 规格必须是 module:function: {spec}")
    module_name, func_name = spec.split(":", 1)
    module = importlib.import_module(module_name)
    fn = getattr(module, func_name)

    if func_name == "register_hooks":
        fn(manager)
        return

    event_type = getattr(fn, "_agent_hook_event", "*")
    manager.register(str(event_type), fn)


def load_hook_specs(manager: HookManager, specs: list[str] | None) -> None:
    for spec in specs or []:
        load_hook_spec(manager, spec)
