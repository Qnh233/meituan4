"""OpenAI 兼容 Chat Completions — 离线 Agent 专用（使用官方 openai SDK）。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CompletionResult:
    """一次 chat completion 的输出与用量（网关无 usage 时 token 计数为 0）。"""

    content: str | None
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


def chat_complete(
    *,
    api_key: str,
    base_url: str,
    model: str,
    messages: list[dict],
    temperature: float = 0.8,
    max_tokens: int = 4096,
    timeout_seconds: float = 120.0,
    reasoning_effort: str | None = None,
    thinking_disabled: bool = False,
) -> CompletionResult | None:
    """调用 OpenAI 兼容的 chat.completions API，返回内容与 usage。"""
    if not api_key:
        print("[LLM] 未配置 API key，跳过请求")
        return None

    try:
        from openai import OpenAI
    except ImportError:
        print("[LLM] 未安装 openai，请 pip install -r requirements-agent.txt")
        return None

    base = (base_url or "").strip()
    kw: dict = {"api_key": api_key, "timeout": timeout_seconds}
    if base:
        kw["base_url"] = base.rstrip("/")

    client = OpenAI(**kw)

    kwargs: dict = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    # DeepSeek: 关闭 thinking；其它 thinking 模型：控制 reasoning 开销
    extra = {}
    if thinking_disabled:
        extra["thinking"] = {"type": "disabled"}
    if reasoning_effort and not thinking_disabled:
        extra["reasoning_effort"] = reasoning_effort
    if extra:
        kwargs["extra_body"] = extra
    # 新版本模型可能需要 max_completion_tokens，失败时降级重试一次
    try:
        resp = client.chat.completions.create(**kwargs)
    except Exception as first_err:
        try:
            kwargs.pop("max_tokens", None)
            kwargs["max_completion_tokens"] = max_tokens
            resp = client.chat.completions.create(**kwargs)
        except Exception:
            print(f"[LLM] 请求失败: {first_err}")
            return None

    pt = ct = tt = 0
    usage = getattr(resp, "usage", None)
    if usage is not None:
        pt = int(getattr(usage, "prompt_tokens", None) or 0)
        ct = int(getattr(usage, "completion_tokens", None) or 0)
        tt = int(getattr(usage, "total_tokens", None) or (pt + ct))

    choices = getattr(resp, "choices", None) or []
    text: str | None = None
    if choices:
        msg = getattr(choices[0], "message", None)
        if msg is not None:
            text = getattr(msg, "content", None)
            if isinstance(text, str):
                text = text.strip() or None
    return CompletionResult(content=text, prompt_tokens=pt, completion_tokens=ct, total_tokens=tt)
