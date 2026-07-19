"""Provider-agnostic LLM gateway — model dispatched by name prefix.

Forked in shape from MIRA's runtime/llm.py + providers.py, trimmed to what
SentinelCall needs: Claude (Anthropic) as the primary reasoning model for the
supervisor + GER + safety gate, with an OpenAI-compatible path retained for any
GPT model and (elsewhere) Whisper STT.

Every agent goes through `llm()` — never a vendor SDK directly. Each call is
cost-metered into obs.trace so the demo can show per-turn spend.
"""
from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

try:
    from pydantic import BaseModel, Field

    class Message(BaseModel):
        role: str  # system | user | assistant | tool
        content: Optional[str] = None
        tool_calls: Optional[List[Dict[str, Any]]] = None
        tool_call_id: Optional[str] = None
        name: Optional[str] = None

    class LLMUsage(BaseModel):
        prompt_tokens: int = 0
        completion_tokens: int = 0
        cached_prompt_tokens: int = 0
        cache_creation_tokens: int = 0
        cost_usd: float = 0.0

    class LLMResponse(BaseModel):
        text: str
        model: str
        provider: str = "anthropic"
        usage: LLMUsage = Field(default_factory=LLMUsage)
        finish_reason: Optional[str] = None
        tool_calls: List[Dict[str, Any]] = Field(default_factory=list)

except Exception:  # pragma: no cover — pydantic-free fallback
    from dataclasses import dataclass, field

    @dataclass
    class Message:  # type: ignore
        role: str
        content: Optional[str] = None
        tool_calls: Optional[List[Dict[str, Any]]] = None
        tool_call_id: Optional[str] = None
        name: Optional[str] = None

        def model_dump(self, exclude_none: bool = False) -> Dict[str, Any]:
            d = {
                "role": self.role,
                "content": self.content,
                "tool_calls": self.tool_calls,
                "tool_call_id": self.tool_call_id,
                "name": self.name,
            }
            return {k: v for k, v in d.items() if not (exclude_none and v is None)}

    @dataclass
    class LLMUsage:  # type: ignore
        prompt_tokens: int = 0
        completion_tokens: int = 0
        cached_prompt_tokens: int = 0
        cache_creation_tokens: int = 0
        cost_usd: float = 0.0

    @dataclass
    class LLMResponse:  # type: ignore
        text: str = ""
        model: str = ""
        provider: str = "anthropic"
        usage: LLMUsage = field(default_factory=LLMUsage)
        finish_reason: Optional[str] = None
        tool_calls: List[Dict[str, Any]] = field(default_factory=list)


from sentinelcall.config import get_settings
from sentinelcall.obs import trace as _trace  # module (not the trace() fn — import path is the submodule)


# Per-1K-token prices (USD). Coarse table for budget estimation, not billing.
_COST_TABLE: Dict[str, tuple] = {
    "claude-opus-4-8": (0.015, 0.075),
    "claude-opus-4-7": (0.015, 0.075),
    "claude-sonnet-5": (0.003, 0.015),
    "claude-sonnet-4-6": (0.003, 0.015),
    "claude-haiku-4-5": (0.001, 0.005),
    "gpt-4o": (0.005, 0.015),
    "gpt-4o-mini": (0.00015, 0.0006),
}
# Anthropic ephemeral cache: reads at 0.10x input, writes at 1.25x.
_CACHE_READ_MULT = {k: 0.1 for k in _COST_TABLE if k.startswith("claude")}
_CACHE_WRITE_MULT = {k: 1.25 for k in _COST_TABLE if k.startswith("claude")}


def _estimate_cost(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    *,
    cached_prompt_tokens: int = 0,
    cache_creation_tokens: int = 0,
) -> float:
    pin, pout = _COST_TABLE.get(model, (0.003, 0.015))
    read_mult = _CACHE_READ_MULT.get(model, 1.0)
    write_mult = _CACHE_WRITE_MULT.get(model, 1.0)
    fresh = max(0, prompt_tokens - cached_prompt_tokens - cache_creation_tokens)
    cost = (fresh / 1000) * pin
    cost += (cached_prompt_tokens / 1000) * pin * read_mult
    cost += (cache_creation_tokens / 1000) * pin * write_mult
    cost += (completion_tokens / 1000) * pout
    return cost


def provider_for(model: str) -> str:
    if model.startswith("claude-"):
        return "anthropic"
    return "openai"  # gpt-, whisper-, and unknown default to OpenAI-compat


# ---------------------------------------------------------------------------
# Anthropic adapter
# ---------------------------------------------------------------------------


class _AnthropicAdapter:
    provider = "anthropic"

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._client: Any = None

    def _get(self) -> Any:
        if self._client is None:
            from anthropic import Anthropic

            self._client = Anthropic(api_key=self._api_key, timeout=30.0)
        return self._client

    def _translate(self, messages: List[Message]):
        system_parts: List[str] = []
        out: List[Dict[str, Any]] = []
        for m in messages:
            if m.role == "system":
                if m.content:
                    system_parts.append(m.content)
                continue
            if m.role == "tool":
                out.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": m.tool_call_id or "",
                                "content": m.content or "",
                            }
                        ],
                    }
                )
                continue
            out.append({"role": m.role, "content": m.content or ""})
        return "\n\n".join(system_parts), out

    def complete(
        self,
        *,
        model: str,
        messages: List[Message],
        temperature: float,
        max_tokens: int,
    ) -> LLMResponse:
        system, msgs = self._translate(messages)
        kwargs: Dict[str, Any] = {
            "model": model,
            "messages": msgs,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system:
            # Cache the (stable) system prompt for cheap re-reads across turns.
            kwargs["system"] = [
                {
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        resp = self._get().messages.create(**kwargs)

        text_parts: List[str] = []
        for block in getattr(resp, "content", []) or []:
            if getattr(block, "type", None) == "text":
                text_parts.append(getattr(block, "text", "") or "")

        usage = getattr(resp, "usage", None)
        pt = getattr(usage, "input_tokens", 0) if usage else 0
        ct = getattr(usage, "output_tokens", 0) if usage else 0
        cache_read = (getattr(usage, "cache_read_input_tokens", 0) if usage else 0) or 0
        cache_write = (getattr(usage, "cache_creation_input_tokens", 0) if usage else 0) or 0

        return LLMResponse(
            text="".join(text_parts),
            model=model,
            provider="anthropic",
            usage=LLMUsage(
                prompt_tokens=pt + cache_read + cache_write,
                completion_tokens=ct,
                cached_prompt_tokens=cache_read,
                cache_creation_tokens=cache_write,
            ),
            finish_reason=getattr(resp, "stop_reason", None),
        )


# ---------------------------------------------------------------------------
# OpenAI-compatible adapter (GPT models; kept minimal)
# ---------------------------------------------------------------------------


class _OpenAICompatAdapter:
    provider = "openai"

    def __init__(self, api_key: str, base_url: Optional[str] = None) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._client: Any = None

    def _get(self) -> Any:
        if self._client is None:
            from openai import OpenAI

            if self._base_url:
                self._client = OpenAI(api_key=self._api_key, base_url=self._base_url, timeout=30.0)
            else:
                self._client = OpenAI(api_key=self._api_key, timeout=30.0)
        return self._client

    def complete(
        self,
        *,
        model: str,
        messages: List[Message],
        temperature: float,
        max_tokens: int,
    ) -> LLMResponse:
        resp = self._get().chat.completions.create(
            model=model,
            messages=[m.model_dump(exclude_none=True) for m in messages],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        choice = resp.choices[0]
        text = choice.message.content or ""
        usage = getattr(resp, "usage", None)
        pt = getattr(usage, "prompt_tokens", 0) if usage else 0
        ct = getattr(usage, "completion_tokens", 0) if usage else 0
        return LLMResponse(
            text=text,
            model=model,
            provider="openai",
            usage=LLMUsage(prompt_tokens=pt, completion_tokens=ct),
            finish_reason=getattr(choice, "finish_reason", None),
        )


# ---------------------------------------------------------------------------
# Gateway
# ---------------------------------------------------------------------------


class LLMGateway:
    def __init__(self) -> None:
        self._settings = get_settings()
        self._anthropic: Optional[_AnthropicAdapter] = None
        self._openai: Optional[_OpenAICompatAdapter] = None

    def _anthropic_adapter(self) -> _AnthropicAdapter:
        if self._anthropic is None:
            key = self._settings.anthropic_api_key
            if not key:
                raise RuntimeError("ANTHROPIC_API_KEY is not set; cannot route to Claude.")
            self._anthropic = _AnthropicAdapter(key)
        return self._anthropic

    def _openai_adapter(self) -> _OpenAICompatAdapter:
        if self._openai is None:
            key = self._settings.openai_api_key
            if not key:
                raise RuntimeError("OPENAI_API_KEY is not set; cannot route to an OpenAI model.")
            self._openai = _OpenAICompatAdapter(key)
        return self._openai

    def _adapter_for(self, model: str):
        return self._anthropic_adapter() if provider_for(model) == "anthropic" else self._openai_adapter()

    def complete(
        self,
        messages: List[Message],
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: int = 800,
    ) -> LLMResponse:
        mdl = model or self._settings.supervisor_model
        temp = self._settings.llm_temperature if temperature is None else temperature
        adapter = self._adapter_for(mdl)
        t0 = time.perf_counter()
        resp = adapter.complete(
            model=mdl, messages=messages, temperature=temp, max_tokens=max_tokens
        )
        if resp.usage.cost_usd == 0.0:
            resp.usage.cost_usd = _estimate_cost(
                mdl,
                resp.usage.prompt_tokens,
                resp.usage.completion_tokens,
                cached_prompt_tokens=resp.usage.cached_prompt_tokens,
                cache_creation_tokens=resp.usage.cache_creation_tokens,
            )
        _trace.record_cost(
            cost_usd=resp.usage.cost_usd,
            prompt_tokens=resp.usage.prompt_tokens,
            completion_tokens=resp.usage.completion_tokens,
        )
        _trace.event(
            "llm.call",
            model=mdl,
            provider=adapter.provider,
            prompt_tokens=resp.usage.prompt_tokens,
            completion_tokens=resp.usage.completion_tokens,
            cost_usd=round(resp.usage.cost_usd, 6),
            latency_ms=round((time.perf_counter() - t0) * 1000, 1),
        )
        return resp

    def complete_json(
        self,
        messages: List[Message],
        *,
        model: Optional[str] = None,
        max_tokens: int = 800,
    ) -> Dict[str, Any]:
        """Complete and parse the reply as JSON. Tolerant of ```json fences.
        Used by GER, safety gate, and structured extraction — all of which
        demand a machine-readable object, not prose."""
        resp = self.complete(messages, model=model, max_tokens=max_tokens)
        return _parse_json_loose(resp.text)


def _parse_json_loose(text: str) -> Dict[str, Any]:
    s = (text or "").strip()
    if s.startswith("```"):
        # strip a ```json ... ``` fence
        s = s.split("```", 2)[1] if s.count("```") >= 2 else s.strip("`")
        if s.startswith("json"):
            s = s[4:]
        s = s.strip()
    # find first { and last } to be forgiving of leading prose
    start = s.find("{")
    end = s.rfind("}")
    if start != -1 and end != -1 and end > start:
        s = s[start : end + 1]
    try:
        return json.loads(s)
    except Exception:
        return {}


_gateway: Optional[LLMGateway] = None


def llm() -> LLMGateway:
    global _gateway
    if _gateway is None:
        _gateway = LLMGateway()
    return _gateway
