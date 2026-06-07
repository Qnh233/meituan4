"""离线 Agent 运行时配置中心化加载。

优先级（后者覆盖前者）：
  1. 内置默认
  2. JSON 文件（``agent/agent_llm.settings.json``，或 CLI ``--settings``）
  3. 环境变量（LLM_API_KEY / LLM_BASE_URL / LLM_MODEL 等）
  4. CLI 显式传参（如 ``--llm-api-key``）

不把密钥写入仓库：复制 ``agent/agent_llm.settings.example.json``
为 ``agent/agent_llm.settings.json``（该文件名建议加入本地 .gitignore）。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

# 默认配置文件（相对仓库根目录）
DEFAULT_SETTINGS_REL = Path("agent/agent_llm.settings.json")


@dataclass
class LLMSettings:
    """与 OpenAI 兼容网关对齐的会话参数（不含业务逻辑）。"""

    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4"
    timeout_seconds: float = 120.0
    # 主生成（策略代码）
    generate_temperature: float = 0.85
    generate_max_tokens: int = 8192
    reasoning_effort: str = ""  # thinking模型：low/medium/high
    thinking_disabled: bool = True  # DeepSeek: 关闭深度思考
    # 修复 / 反思等相对低温
    repair_temperature: float = 0.3
    repair_max_tokens: int = 4096
    reflect_temperature: float = 0.35
    reflect_max_tokens: int = 2048


@dataclass
class ExplorationSettings:
    """控制「本轮探索方向」如何进入 prompt——与是否调用 LLM 无关。"""

    # heuristic: 走 extract_direction 规则采样（偏向经验与 tag 覆盖率）
    # open: 不注入 ## 本轮探索方向，仅靠经验池 + Top-K，由模型自拟方向
    direction_mode: str = "heuristic"


@dataclass
class AgentRuntimeBundle:
    """CLI / search_loop / graph 共用的单行配置载荷。"""

    llm: LLMSettings = field(default_factory=LLMSettings)
    exploration: ExplorationSettings = field(default_factory=ExplorationSettings)


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def load_json_file(path: Path) -> dict:
    """读取 JSON；文件不存在或非 dict 返回空 dict。"""
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _env_llm_overlay() -> dict:
    """从环境变量覆盖（不写死在代码里即可部署到 CI/CD）。"""
    out = {}
    if os.environ.get("LLM_API_KEY"):
        out["api_key"] = os.environ["LLM_API_KEY"]
    if os.environ.get("LLM_BASE_URL"):
        out["base_url"] = os.environ["LLM_BASE_URL"]
    if os.environ.get("LLM_MODEL"):
        out["model"] = os.environ["LLM_MODEL"]
    ts = os.environ.get("LLM_TIMEOUT_SECONDS")
    if ts:
        try:
            out["timeout_seconds"] = float(ts)
        except ValueError:
            pass
    return {"llm": out} if out else {}


def _coerce_llm_field(name: str, value: object) -> object:
    """JSON 常为 int/str 混写，统一到 LLMSettings 期望类型。"""
    if value is None:
        return None
    if name in {"generate_max_tokens", "repair_max_tokens", "reflect_max_tokens"}:
        return int(value)
    if name in {"timeout_seconds", "generate_temperature", "repair_temperature", "reflect_temperature"}:
        return float(value)
    if name == "api_key":
        return str(value)
    if name == "model":
        return str(value).strip()
    if name == "base_url":
        return str(value).strip().rstrip("/")
    if name == "reasoning_effort":
        return str(value).strip()
    if name == "thinking_disabled":
        return bool(value)
    return value


def _normalize_direction_mode(mode: object) -> str:
    raw = str(mode or "").strip().lower()
    if raw in {"", "heuristic", "wrapped", "rules"}:
        return "heuristic"
    if raw in {"open", "free", "llm"}:
        return "open"
    print(f"[settings] 未知 exploration.direction_mode={mode!r}，改用 heuristic")
    return "heuristic"


def merge_runtime_bundle(
    *,
    settings_file: Path | None = None,
    cli_llm_patch: dict | None = None,
    cli_direction_mode: str | None = None,
) -> AgentRuntimeBundle:
    """装载合并后的运行时配置。"""
    path = settings_file if settings_file is not None else _repo_root() / DEFAULT_SETTINGS_REL
    file_payload = load_json_file(path)

    bundle = AgentRuntimeBundle()

    # 文件 → llm（忽略 _ 前缀键与未知字段）
    lm = file_payload.get("llm") or {}
    llm_allow = frozenset(LLMSettings.__dataclass_fields__)
    if isinstance(lm, dict):
        for k, v in lm.items():
            if not isinstance(k, str) or k.startswith("_"):
                continue
            if k not in llm_allow:
                continue
            if v is None or v == "":
                continue
            setattr(bundle.llm, k, _coerce_llm_field(k, v))

    ex = file_payload.get("exploration") or {}
    if isinstance(ex, dict):
        dm = ex.get("direction_mode")
        if dm is not None and str(dm).strip():
            bundle.exploration.direction_mode = _normalize_direction_mode(dm)

    # 环境覆盖文件（无值不写）
    env_payload = _env_llm_overlay()
    el = env_payload.get("llm") or {}
    for k, v in el.items():
        if k not in llm_allow or v is None or v == "":
            continue
        setattr(bundle.llm, k, _coerce_llm_field(k, v))

    # CLI 覆盖（通常为 api_key/base_url/model）
    if cli_llm_patch:
        for k, v in cli_llm_patch.items():
            if v is None or v == "":
                continue
            if k not in llm_allow:
                continue
            setattr(bundle.llm, k, _coerce_llm_field(k, v))

    if cli_direction_mode is not None and str(cli_direction_mode).strip():
        bundle.exploration.direction_mode = str(cli_direction_mode).strip()

    bundle.exploration.direction_mode = _normalize_direction_mode(
        bundle.exploration.direction_mode,
    )

    # 兜底：仍为空的 endpoint 前缀
    if not bundle.llm.base_url:
        bundle.llm.base_url = "https://api.openai.com/v1"

    return bundle
