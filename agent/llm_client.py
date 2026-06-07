"""LLM 客户端。

- live：通过 OpenAI 官方 SDK 调用兼容网关（参见 agent/openai_chat.py）
- dry_run：不调 API，模板策略走 generate_dry_run_strategy（用于无 Key 自检）
- 会话级超参（temperature、max_tokens 等）应由 ``agent/settings.LLMSettings``
  经 ``merge_runtime_bundle`` 中心化合并后传入 ``settings=``。
"""

from __future__ import annotations

import os
from dataclasses import replace

from agent.openai_chat import CompletionResult, chat_complete
from agent.settings import LLMSettings


class LLMClient:
    def __init__(
        self,
        *,
        settings: LLMSettings | None = None,
        dry_run: bool = False,
        # --- 兼容旧调用：未传 settings 时由下列字段构造 LLMSettings ---
        api_key: str = "",
        base_url: str = "",
        model: str = "",
        timeout_seconds: float = 120.0,
    ):
        if settings is None:
            settings = LLMSettings(
                api_key=api_key,
                base_url=base_url or "https://api.openai.com/v1",
                model=model or "gpt-4",
                timeout_seconds=timeout_seconds,
            )
        # 文件/合并结果之后，仍允许用环境变量兜底（便于临时跑通）
        ak = (settings.api_key or os.environ.get("LLM_API_KEY", "") or "").strip()
        bu = (
            settings.base_url.strip()
            or os.environ.get("LLM_BASE_URL", "")
            or ""
        ).strip().rstrip("/")
        if not bu:
            bu = "https://api.openai.com/v1"
        md = (settings.model or os.environ.get("LLM_MODEL", "") or "gpt-4").strip()
        self.settings = replace(
            settings,
            api_key=ak,
            base_url=bu,
            model=md,
        )
        self.dry_run = dry_run

    @property
    def api_key(self) -> str:
        return self.settings.api_key

    @property
    def base_url(self) -> str:
        return self.settings.base_url

    @property
    def model(self) -> str:
        return self.settings.model

    @property
    def timeout_seconds(self) -> float:
        return float(self.settings.timeout_seconds)

    def complete(
        self,
        messages: list[dict],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        reasoning_effort: str | None = None,
        thinking_disabled: bool | None = None,
    ) -> CompletionResult | None:
        """进行一次 chat completion。"""
        if self.dry_run:
            return None
        if not self.api_key:
            print("[LLM] 无 API key；请配置 agent_llm.settings.json 或 LLM_API_KEY")
            return None

        t = (
            float(self.settings.generate_temperature)
            if temperature is None
            else float(temperature)
        )
        mt = (
            int(self.settings.generate_max_tokens)
            if max_tokens is None
            else int(max_tokens)
        )
        re = (
            str(self.settings.reasoning_effort).strip()
            if reasoning_effort is None
            else str(reasoning_effort).strip()
        ) or None
        td = (
            bool(getattr(self.settings, "thinking_disabled", False))
            if thinking_disabled is None
            else bool(thinking_disabled)
        )

        return chat_complete(
            api_key=self.api_key,
            base_url=self.base_url,
            model=self.model,
            messages=messages,
            temperature=t,
            max_tokens=mt,
            timeout_seconds=self.timeout_seconds,
            reasoning_effort=re,
            thinking_disabled=td,
        )

    def chat(
        self,
        messages: list[dict],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str | None:
        """兼容旧接口：仅返回文本。"""
        r = self.complete(messages, temperature=temperature, max_tokens=max_tokens)
        return r.content if r else None


# 模板策略池：dry-run 模式下返回的伪策略代码
TEMPLATE_STRATEGIES = [
    {
        "name": "GreedyComposite",
        "description": "复合贪心：先按 willingness 选高分候选，剩余用 score 补全",
        "sort_key": "composite",
        "rationale": "试验意愿×成本加权组合排序能否比纯意愿排序降低总成本",
    },
    {
        "name": "TwoPhase",
        "description": "两阶段：第一阶段选 willingness>0.5 的候选，第二阶段用 unit_score 补全",
        "sort_key": "two_phase",
        "rationale": "检验两阶段分离（先保证覆盖率再优化成本）是否优于单阶段混合排序",
    },
    {
        "name": "BestPerTask",
        "description": "逐任务贪心：对每个未覆盖任务选最优候选，按 score 升序",
        "sort_key": "per_task",
        "rationale": "逐任务视角分配，验证按任务维度贪心 vs 全局候选排序的差异",
    },
    {
        "name": "ConfidenceFirst",
        "description": "信心优先：willingness>0.7 的直分配，剩余用 ratio 贪心",
        "sort_key": "confidence",
        "rationale": "测试高信心阈值策略：高意愿骑手廉价分配，低意愿骑手按性价比补全",
    },
    {
        "name": "ScoreOptimized",
        "description": "成本优化：按 unit_score 升序，但跳过 willingness<0.1 的候选",
        "sort_key": "score_opt",
        "rationale": "极致成本导向：unit_score 排序，仅排除几乎确定不接单的骑手",
    },
]

_template_idx = 0


def generate_dry_run_strategy() -> dict:
    """dry-run：从模板池轮转返回策略规格（等价于伪造 LLM 输出）。"""
    global _template_idx
    t = TEMPLATE_STRATEGIES[_template_idx % len(TEMPLATE_STRATEGIES)]
    _template_idx += 1

    return {
        "name": t["name"],
        "description": t["description"],
        "sort_key": t["sort_key"],
        "rationale": t.get("rationale", ""),
    }
