"""Fail-closed DeepSeek provider for bounded NEXUS research assistance.

Paid routing uses an atomic reservation ledger. Every request reserves a conservative
worst-case input+output cost before network I/O. Ambiguous requests keep their
reservation quarantined, so retries cannot spend the same budget slice twice.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
from typing import Any
from urllib import request
from uuid import uuid4

BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-flash"
PRO_MODEL = "deepseek-v4-pro"
ALLOWED_MODELS = {DEFAULT_MODEL, PRO_MODEL}
MONTHLY_BUDGET_USD = 5.00
RESERVE_USD = 0.50
PRICING_VERSION = "2026-08-09"
LEDGER_SCHEMA = 2
CANONICAL_LEDGER = Path("build/deepseek/usage.json")
PRICING = {
    DEFAULT_MODEL: {"cache_hit": 0.0028, "cache_miss": 0.14, "output": 0.28},
    PRO_MODEL: {"cache_hit": 0.003625, "cache_miss": 0.435, "output": 0.87},
}


class DeepSeekError(RuntimeError):
    pass


class BudgetExceeded(DeepSeekError):
    pass


class AmbiguousCharge(DeepSeekError):
    pass


@dataclass(frozen=True)
class RouteDecision:
    model: str
    thinking: bool
    reasoning_effort: str | None


def route_task(*, complexity: str = "routine", blocker: bool = False) -> RouteDecision:
    if complexity not in {"routine", "complex", "critical"}:
        raise ValueError("unknown complexity")
    if blocker or complexity == "critical":
        return RouteDecision(PRO_MODEL, True, "high")
    if complexity == "complex":
        return RouteDecision(DEFAULT_MODEL, True, "high")
    return RouteDecision(DEFAULT_MODEL, False, None)


def _month_key(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m")


def _canonical_path(path: str | Path) -> Path:
    p = Path(path)
    if p != CANONICAL_LEDGER:
        raise DeepSeekError("alternate usage ledger path is not authorized")
    return p


def _fresh_ledger() -> dict[str, Any]:
    return {
        "schema_version": LEDGER_SCHEMA,
        "month": _month_key(),
        "pricing_version": PRICING_VERSION,
        "spent_usd": 0.0,
        "reserved_usd": 0.0,
        "requests": 0,
        "inflight": {},
    }


def _validate_ledger(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise DeepSeekError("usage ledger is malformed")
    if data.get("schema_version") != LEDGER_SCHEMA:
        raise DeepSeekError("usage ledger schema is stale or unknown")
    if data.get("pricing_version") != PRICING_VERSION:
        raise DeepSeekError("usage ledger pricing version is stale or unknown")
    for key in ("spent_usd", "reserved_usd"):
        value = data.get(key)
        if not isinstance(value, (int, float)) or value < 0:
            raise DeepSeekError("usage ledger accounting is malformed")
    if not isinstance(data.get("requests"), int) or data["requests"] < 0:
        raise DeepSeekError("usage ledger request count is malformed")
    if not isinstance(data.get("inflight"), dict):
        raise DeepSeekError("usage ledger inflight state is malformed")
    expected_reserved = 0.0
    for rec in data["inflight"].values():
        if not isinstance(rec, dict) or not isinstance(rec.get("reserved_usd"), (int, float)) or rec["reserved_usd"] < 0:
            raise DeepSeekError("usage ledger reservation is malformed")
        expected_reserved += float(rec["reserved_usd"])
    if abs(expected_reserved - float(data["reserved_usd"])) > 1e-7:
        raise DeepSeekError("usage ledger reservation total is inconsistent")
    if float(data["spent_usd"]) + float(data["reserved_usd"]) > MONTHLY_BUDGET_USD + 1e-9:
        raise DeepSeekError("usage ledger exceeds configured monthly cap")
    return data


def load_ledger(path: str | Path = CANONICAL_LEDGER) -> dict[str, Any]:
    p = Path(path)
    sentinel = p.with_suffix(p.suffix + ".initialized")
    if not p.exists():
        if sentinel.exists():
            raise DeepSeekError("usage ledger missing after prior initialization")
        return _fresh_ledger()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeepSeekError("usage ledger is unreadable") from exc
    data = _validate_ledger(data)
    if data.get("month") != _month_key():
        if data["inflight"]:
            raise DeepSeekError("month rollover blocked by unresolved request")
        return _fresh_ledger()
    return data


def _sync_file(path: Path) -> None:
    """Flush one writable file handle before paid network I/O can proceed."""
    with path.open("r+b") as handle:
        os.fsync(handle.fileno())


def _sync_parent_directory(path: Path) -> None:
    """Persist rename/create metadata where directory fsync is supported.

    Windows does not expose a portable directory fsync through Python's stdlib. On
    Windows we fsync the replaced file and sentinel themselves and keep paid-routing
    authority non-authoritative until crash/restart recovery is proven on that OS.
    """
    if os.name == "nt":
        return
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    fd = os.open(path.parent, flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def save_ledger(path: str | Path, ledger: dict[str, Any]) -> None:
    p = Path(path)
    _validate_ledger(ledger)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    payload = json.dumps(ledger, sort_keys=True, indent=2)
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, p)
        _sync_file(p)
        _sync_parent_directory(p)

        sentinel = p.with_suffix(p.suffix + ".initialized")
        with sentinel.open("a+b") as handle:
            handle.flush()
            os.fsync(handle.fileno())
        _sync_parent_directory(sentinel)
    except OSError as exc:
        raise DeepSeekError("usage ledger durability commit failed") from exc


@contextmanager
def _ledger_lock(path: Path, timeout: float = 10.0):
    lock = path.with_suffix(path.suffix + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    fd = None
    while fd is None:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise DeepSeekError("usage ledger is locked or recovery is required")
            time.sleep(0.05)
    try:
        os.write(fd, str(os.getpid()).encode("ascii", "ignore"))
        os.close(fd)
        fd = None
        yield
    finally:
        if fd is not None:
            os.close(fd)
        try:
            lock.unlink()
        except FileNotFoundError:
            pass


def calculate_cost(model: str, usage: dict[str, Any]) -> float:
    if model not in PRICING:
        raise DeepSeekError("unknown model pricing")
    if any(k not in usage for k in ("prompt_tokens", "completion_tokens")):
        raise DeepSeekError("usage counters are missing")
    try:
        prompt = int(usage["prompt_tokens"])
        output = int(usage["completion_tokens"])
        hit = int(usage.get("prompt_cache_hit_tokens", 0) or 0)
        miss = int(usage.get("prompt_cache_miss_tokens", prompt - hit) or 0)
    except (TypeError, ValueError) as exc:
        raise DeepSeekError("usage counters are malformed") from exc
    if min(prompt, output, hit, miss) < 0 or hit + miss != prompt:
        raise DeepSeekError("usage counters are inconsistent")
    prices = PRICING[model]
    return (hit * prices["cache_hit"] + miss * prices["cache_miss"] + output * prices["output"]) / 1_000_000


def remaining_budget(ledger: dict[str, Any]) -> float:
    return max(MONTHLY_BUDGET_USD - float(ledger["spent_usd"]) - float(ledger["reserved_usd"]), 0.0)


def _worst_case_reservation(model: str, messages: list[dict[str, str]], max_tokens: int) -> tuple[int, float]:
    if model not in ALLOWED_MODELS:
        raise DeepSeekError("unknown model")
    if not isinstance(max_tokens, int) or max_tokens <= 0 or max_tokens > 32768:
        raise DeepSeekError("max_tokens outside NEXUS bound")
    if not isinstance(messages, list) or not messages:
        raise DeepSeekError("messages must be a non-empty list")
    payload_bytes = len(json.dumps(messages, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    worst_input_tokens = payload_bytes + 2048
    price = PRICING[model]
    reserve = (worst_input_tokens * price["cache_miss"] + max_tokens * price["output"]) / 1_000_000
    return worst_input_tokens, reserve


def _reserve(path: Path, model: str, messages: list[dict[str, str]], max_tokens: int, blocker: bool) -> tuple[str, float]:
    _, amount = _worst_case_reservation(model, messages, max_tokens)
    with _ledger_lock(path):
        ledger = load_ledger(path)
        usable_cap = MONTHLY_BUDGET_USD if blocker else MONTHLY_BUDGET_USD - RESERVE_USD
        committed = float(ledger["spent_usd"]) + float(ledger["reserved_usd"])
        if committed + amount > usable_cap + 1e-12:
            raise BudgetExceeded("DeepSeek monthly budget/reserve exhausted")
        request_id = uuid4().hex
        ledger["inflight"][request_id] = {
            "reserved_usd": round(amount, 10),
            "model": model,
            "pricing_version": PRICING_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "reserved",
        }
        ledger["reserved_usd"] = round(float(ledger["reserved_usd"]) + amount, 10)
        save_ledger(path, ledger)
        return request_id, amount


def _reconcile(path: Path, request_id: str, model: str, usage: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    actual = calculate_cost(model, usage)
    with _ledger_lock(path):
        ledger = load_ledger(path)
        rec = ledger["inflight"].get(request_id)
        if rec is None:
            raise DeepSeekError("reservation missing during reconciliation")
        reserved = float(rec["reserved_usd"])
        if actual > reserved + 1e-9:
            rec["status"] = "quarantined_actual_exceeds_reservation"
            save_ledger(path, ledger)
            raise AmbiguousCharge("provider usage exceeded conservative reservation")
        ledger["reserved_usd"] = round(float(ledger["reserved_usd"]) - reserved, 10)
        ledger["spent_usd"] = round(float(ledger["spent_usd"]) + actual, 10)
        ledger["requests"] += 1
        ledger["last_model"] = model
        ledger["last_cost_usd"] = round(actual, 10)
        del ledger["inflight"][request_id]
        save_ledger(path, ledger)
        return actual, ledger


def chat(
    messages: list[dict[str, str]],
    *,
    complexity: str = "routine",
    blocker: bool = False,
    max_tokens: int = 1024,
    ledger_path: str | Path = CANONICAL_LEDGER,
    timeout: float = 90.0,
) -> dict[str, Any]:
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        raise DeepSeekError("DEEPSEEK_API_KEY is missing")
    decision = route_task(complexity=complexity, blocker=blocker)
    path = _canonical_path(ledger_path)
    request_id, _ = _reserve(path, decision.model, messages, max_tokens, blocker)

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
    except Exception:
        raise AmbiguousCharge("DeepSeek request outcome is ambiguous; reservation retained") from None

    choices, usage = payload.get("choices"), payload.get("usage")
    if not isinstance(choices, list) or not choices or not isinstance(usage, dict):
        raise AmbiguousCharge("DeepSeek response missing choices or usage; reservation retained")
    content = ((choices[0] or {}).get("message") or {}).get("content")
    if not isinstance(content, str):
        raise AmbiguousCharge("DeepSeek response missing text content; reservation retained")
    cost, ledger = _reconcile(path, request_id, decision.model, usage)
    return {
        "content": content,
        "model": decision.model,
        "thinking": decision.thinking,
        "cost_usd": cost,
        "month_spent_usd": ledger["spent_usd"],
        "month_remaining_usd": round(remaining_budget(ledger), 10),
    }
