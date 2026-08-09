"""Bounded DeepSeek provider for NEXUS research/development assistance.

No production/trading authority is granted by this module. The API key is read only
from DEEPSEEK_API_KEY and is never persisted or included in exceptions/log payloads.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any
from urllib import error, request

BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-flash"
PRO_MODEL = "deepseek-v4-pro"
ALLOWED_MODELS = {DEFAULT_MODEL, PRO_MODEL}
MONTHLY_BUDGET_USD = 5.00
RESERVE_USD = 0.50
PRICING_VERSION = "2026-08-09"
MAX_INPUT_BYTES = 131_072
PROMPT_TOKEN_OVERHEAD = 256
PER_MESSAGE_TOKEN_OVERHEAD = 64
# USD per 1M tokens: cache-hit input, cache-miss input, output.
PRICING = {
    DEFAULT_MODEL: {"cache_hit": 0.0028, "cache_miss": 0.14, "output": 0.28},
    PRO_MODEL: {"cache_hit": 0.003625, "cache_miss": 0.435, "output": 0.87},
}


class DeepSeekError(RuntimeError):
    """Safe provider error. Never embed secret material in messages."""


class BudgetExceeded(DeepSeekError):
    pass


@dataclass(frozen=True)
class RouteDecision:
    model: str
    thinking: bool
    reasoning_effort: str | None


def route_task(*, complexity: str = "routine", blocker: bool = False) -> RouteDecision:
    """Cost-aware route: Flash by default; Pro only for high-value hard work."""
    if complexity not in {"routine", "complex", "critical"}:
        raise ValueError("unknown complexity")
    if blocker or complexity == "critical":
        return RouteDecision(PRO_MODEL, True, "high")
    if complexity == "complex":
        return RouteDecision(DEFAULT_MODEL, True, "high")
    return RouteDecision(DEFAULT_MODEL, False, None)


def _month_key(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return now.strftime("%Y-%m")


def load_ledger(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {"month": _month_key(), "pricing_version": PRICING_VERSION, "spent_usd": 0.0, "requests": 0}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeepSeekError("usage ledger is unreadable") from exc
    if data.get("month") != _month_key():
        return {"month": _month_key(), "pricing_version": PRICING_VERSION, "spent_usd": 0.0, "requests": 0}
    if data.get("pricing_version") != PRICING_VERSION:
        raise DeepSeekError("usage ledger pricing version is stale or unknown")
    return data


def save_ledger(path: str | Path, ledger: dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(ledger, sort_keys=True, indent=2), encoding="utf-8")
    tmp.replace(p)


def calculate_cost(model: str, usage: dict[str, Any]) -> float:
    if model not in PRICING:
        raise DeepSeekError("unknown model pricing")
    prompt = int(usage.get("prompt_tokens", 0) or 0)
    hit = int(usage.get("prompt_cache_hit_tokens", 0) or 0)
    miss_raw = usage.get("prompt_cache_miss_tokens")
    miss = int(miss_raw if miss_raw is not None else max(prompt - hit, 0))
    output = int(usage.get("completion_tokens", 0) or 0)
    if min(prompt, hit, miss, output) < 0 or hit > prompt or hit + miss < prompt:
        raise DeepSeekError("invalid usage counters")
    prices = PRICING[model]
    return (hit * prices["cache_hit"] + miss * prices["cache_miss"] + output * prices["output"]) / 1_000_000


def remaining_budget(ledger: dict[str, Any]) -> float:
    return max(MONTHLY_BUDGET_USD - float(ledger.get("spent_usd", 0.0)), 0.0)


def _conservative_input_token_bound(messages: list[dict[str, str]]) -> int:
    if not isinstance(messages, list) or not messages:
        raise DeepSeekError("messages must be a non-empty list")
    for message in messages:
        if not isinstance(message, dict) or not isinstance(message.get("role"), str) or not isinstance(message.get("content"), str):
            raise DeepSeekError("message schema invalid")
    encoded = json.dumps(messages, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(encoded) > MAX_INPUT_BYTES:
        raise DeepSeekError("prompt exceeds NEXUS input byte bound")
    # UTF-8 byte count is used as a conservative tokenizer-independent upper bound,
    # plus explicit framing overhead for provider-side chat serialization.
    return len(encoded) + PROMPT_TOKEN_OVERHEAD + PER_MESSAGE_TOKEN_OVERHEAD * len(messages)


def _check_preflight_budget(
    ledger: dict[str, Any],
    model: str,
    max_tokens: int,
    *,
    input_token_bound: int = 0,
    blocker: bool = False,
) -> float:
    if model not in ALLOWED_MODELS:
        raise DeepSeekError("unknown model")
    if max_tokens <= 0 or max_tokens > 32768:
        raise DeepSeekError("max_tokens outside NEXUS bound")
    if input_token_bound < 0:
        raise DeepSeekError("input token bound invalid")
    prices = PRICING[model]
    # Treat all input as cache-miss and reserve full requested output: this is intentionally conservative.
    worst_input = input_token_bound * prices["cache_miss"] / 1_000_000
    worst_output = max_tokens * prices["output"] / 1_000_000
    reservation = worst_input + worst_output
    available = remaining_budget(ledger)
    if available <= 0 or reservation > available:
        raise BudgetExceeded("DeepSeek monthly budget exhausted")
    routine_available = max(available - RESERVE_USD, 0.0)
    if not blocker and reservation > routine_available:
        raise BudgetExceeded("DeepSeek reserve protected for blocker/debug work")
    return reservation


def chat(
    messages: list[dict[str, str]],
    *,
    complexity: str = "routine",
    blocker: bool = False,
    max_tokens: int = 1024,
    ledger_path: str | Path = "build/deepseek/usage.json",
    timeout: float = 90.0,
) -> dict[str, Any]:
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        raise DeepSeekError("DEEPSEEK_API_KEY is missing")
    decision = route_task(complexity=complexity, blocker=blocker)
    ledger = load_ledger(ledger_path)
    input_token_bound = _conservative_input_token_bound(messages)
    reservation = _check_preflight_budget(
        ledger,
        decision.model,
        max_tokens,
        input_token_bound=input_token_bound,
        blocker=blocker,
    )

    body: dict[str, Any] = {
        "model": decision.model,
        "messages": messages,
        "max_tokens": max_tokens,
        "thinking": {"type": "enabled" if decision.thinking else "disabled"},
    }
    if decision.reasoning_effort:
        body["reasoning_effort"] = decision.reasoning_effort

    req = request.Request(
        f"{BASE_URL}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        raise DeepSeekError(f"DeepSeek API HTTP {exc.code}") from None
    except (error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise DeepSeekError("DeepSeek API unavailable or malformed response") from exc

    choices = payload.get("choices")
    usage = payload.get("usage")
    if not isinstance(choices, list) or not choices or not isinstance(usage, dict):
        raise DeepSeekError("DeepSeek response missing choices or usage")
    content = ((choices[0] or {}).get("message") or {}).get("content")
    if not isinstance(content, str):
        raise DeepSeekError("DeepSeek response missing text content")

    cost = calculate_cost(decision.model, usage)
    if cost > reservation + 1e-9:
        raise BudgetExceeded("DeepSeek usage exceeded conservative reservation")
    spent = float(ledger.get("spent_usd", 0.0)) + cost
    if spent > MONTHLY_BUDGET_USD + 1e-9:
        raise BudgetExceeded("DeepSeek response would exceed monthly budget")
    ledger.update(
        {
            "month": _month_key(),
            "pricing_version": PRICING_VERSION,
            "spent_usd": round(spent, 8),
            "requests": int(ledger.get("requests", 0)) + 1,
            "last_model": decision.model,
            "last_cost_usd": round(cost, 8),
            "last_reserved_usd": round(reservation, 8),
            "last_input_token_bound": input_token_bound,
        }
    )
    save_ledger(ledger_path, ledger)
    return {
        "content": content,
        "model": decision.model,
        "thinking": decision.thinking,
        "cost_usd": cost,
        "month_spent_usd": ledger["spent_usd"],
        "month_remaining_usd": round(remaining_budget(ledger), 8),
    }
