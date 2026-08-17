from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

POLICY_VERSION = "phase4-resource/v1"
MAX_MEASUREMENT_SAMPLES = 4096


class ResourceBoundError(ValueError):
    pass


class ResourceExhausted(ResourceBoundError):
    pass


@dataclass(frozen=True)
class MetricLimit:
    metric: str
    unit: str
    soft_limit: int
    hard_limit: int

    def __post_init__(self) -> None:
        if not self.metric or not self.unit:
            raise ResourceBoundError("metric and unit are required")
        if isinstance(self.soft_limit, bool) or isinstance(self.hard_limit, bool):
            raise ResourceBoundError("limits must be integers")
        if not isinstance(self.soft_limit, int) or not isinstance(self.hard_limit, int):
            raise ResourceBoundError("limits must be integers")
        if self.soft_limit < 0 or self.hard_limit < self.soft_limit:
            raise ResourceBoundError("resource limits are invalid")


@dataclass(frozen=True)
class ResourceDecision:
    metric: str
    measured: int
    unit: str
    action: str
    reason_code: str
    policy_version: str = POLICY_VERSION


@dataclass(frozen=True)
class MeasurementSummary:
    metric: str
    unit: str
    count: int
    minimum: int
    maximum: int
    p50: int
    p95: int


DEFAULT_LIMITS = {
    "api_latency_ms": MetricLimit("api_latency_ms", "ms", 750, 2_000),
    "dashboard_latency_ms": MetricLimit("dashboard_latency_ms", "ms", 500, 1_500),
    "ai_chat_timeout_ms": MetricLimit("ai_chat_timeout_ms", "ms", 20_000, 45_000),
    "agent_timeout_ms": MetricLimit("agent_timeout_ms", "ms", 45_000, 120_000),
    "queue_latency_ms": MetricLimit("queue_latency_ms", "ms", 10_000, 30_000),
    "replay_processing_ms": MetricLimit("replay_processing_ms", "ms", 2_500, 10_000),
    "backtest_runtime_ms": MetricLimit("backtest_runtime_ms", "ms", 120_000, 300_000),
    "research_runtime_ms": MetricLimit("research_runtime_ms", "ms", 180_000, 600_000),
    "storage_bytes": MetricLimit("storage_bytes", "bytes", 1_073_741_824, 2_147_483_648),
    "log_retention_days": MetricLimit("log_retention_days", "days", 21, 30),
    "runner_concurrency": MetricLimit("runner_concurrency", "workers", 3, 4),
    "provider_spend_microusd": MetricLimit("provider_spend_microusd", "microUSD", 2_000_000, 5_000_000),
    "provider_tokens": MetricLimit("provider_tokens", "tokens", 100_000, 250_000),
    "cpu_millis": MetricLimit("cpu_millis", "millicores", 4_000, 8_000),
    "memory_bytes": MetricLimit("memory_bytes", "bytes", 1_073_741_824, 2_147_483_648),
    "job_runtime_ms": MetricLimit("job_runtime_ms", "ms", 300_000, 900_000),
}
REQUIRED_METRICS = frozenset(DEFAULT_LIMITS)


def _measurement(value: Any, field: str = "measurement") -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ResourceBoundError(f"{field} must be a non-negative integer")
    return value


class ResourceGuard:
    """Versioned soft/hard resource bounds. Exceeding a bound never increases authority."""

    def __init__(self, limits: Mapping[str, MetricLimit] = DEFAULT_LIMITS) -> None:
        if not isinstance(limits, Mapping) or set(limits) != REQUIRED_METRICS:
            raise ResourceBoundError("resource policy must define the complete frozen metric set")
        self._limits = dict(limits)
        for key, limit in self._limits.items():
            if key != limit.metric:
                raise ResourceBoundError("resource policy metric key mismatch")

    @property
    def limits(self) -> Mapping[str, MetricLimit]:
        return dict(self._limits)

    def evaluate(self, metric: str, measured: int) -> ResourceDecision:
        if metric not in self._limits:
            raise ResourceBoundError("unknown resource metric fails closed")
        measured = _measurement(measured)
        limit = self._limits[metric]
        if measured <= limit.soft_limit:
            return ResourceDecision(metric, measured, limit.unit, "allow", "within_soft_limit")
        if measured <= limit.hard_limit:
            return ResourceDecision(metric, measured, limit.unit, "degrade", "soft_limit_exceeded")
        return ResourceDecision(metric, measured, limit.unit, "deny", "hard_limit_exceeded")

    def require_not_exhausted(self, metric: str, measured: int) -> ResourceDecision:
        decision = self.evaluate(metric, measured)
        if decision.action == "deny":
            raise ResourceExhausted(f"{metric}:hard_limit_exceeded")
        return decision


class MeasurementWindow:
    """Bounded integer-only telemetry window for deterministic percentile evidence."""

    def __init__(self, metric: str, unit: str, *, capacity: int = 1024) -> None:
        if not metric or not unit:
            raise ResourceBoundError("metric and unit are required")
        if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 1 or capacity > MAX_MEASUREMENT_SAMPLES:
            raise ResourceBoundError("measurement capacity is outside bounded range")
        self.metric = metric
        self.unit = unit
        self.capacity = capacity
        self._values: list[int] = []
        self._lock = threading.RLock()

    def add(self, measured: int) -> None:
        measured = _measurement(measured)
        with self._lock:
            if len(self._values) >= self.capacity:
                raise ResourceExhausted("measurement_window_capacity_exhausted")
            self._values.append(measured)

    @staticmethod
    def _nearest_rank(values: list[int], percentile: int) -> int:
        if not values:
            raise ResourceBoundError("cannot summarize an empty measurement window")
        ordered = sorted(values)
        rank = max(1, (percentile * len(ordered) + 99) // 100)
        return ordered[rank - 1]

    def summary(self) -> MeasurementSummary:
        with self._lock:
            if not self._values:
                raise ResourceBoundError("cannot summarize an empty measurement window")
            values = list(self._values)
        return MeasurementSummary(
            metric=self.metric,
            unit=self.unit,
            count=len(values),
            minimum=min(values),
            maximum=max(values),
            p50=self._nearest_rank(values, 50),
            p95=self._nearest_rank(values, 95),
        )


class ConcurrencyBudget:
    """Non-blocking bounded runner/worker budget; overload is denied immediately."""

    def __init__(self, hard_limit: int) -> None:
        if isinstance(hard_limit, bool) or not isinstance(hard_limit, int) or hard_limit < 1:
            raise ResourceBoundError("concurrency hard limit must be positive")
        self.hard_limit = hard_limit
        self._active: set[str] = set()
        self._lock = threading.RLock()

    @property
    def active(self) -> int:
        with self._lock:
            return len(self._active)

    def acquire(self, work_id: str) -> int:
        if not isinstance(work_id, str) or not work_id or len(work_id) > 256:
            raise ResourceBoundError("work_id must be a bounded string")
        with self._lock:
            if work_id in self._active:
                return len(self._active)
            if len(self._active) >= self.hard_limit:
                raise ResourceExhausted("runner_concurrency:hard_limit_exceeded")
            self._active.add(work_id)
            return len(self._active)

    def release(self, work_id: str) -> int:
        with self._lock:
            if work_id not in self._active:
                raise ResourceBoundError("cannot release unowned work slot")
            self._active.remove(work_id)
            return len(self._active)


class QuotaBudget:
    """Atomic monotonic quota for tokens/spend/storage-style consumable resources."""

    def __init__(self, *, name: str, hard_limit: int) -> None:
        if not name:
            raise ResourceBoundError("quota name is required")
        self.name = name
        self.hard_limit = _measurement(hard_limit, "hard_limit")
        self._used = 0
        self._reservations: dict[str, int] = {}
        self._lock = threading.RLock()

    @property
    def used(self) -> int:
        with self._lock:
            return self._used

    @property
    def remaining(self) -> int:
        with self._lock:
            return self.hard_limit - self._used

    def reserve(self, reservation_id: str, amount: int) -> int:
        if not isinstance(reservation_id, str) or not reservation_id or len(reservation_id) > 256:
            raise ResourceBoundError("reservation_id must be bounded")
        amount = _measurement(amount, "amount")
        if amount < 1:
            raise ResourceBoundError("reservation amount must be positive")
        with self._lock:
            existing = self._reservations.get(reservation_id)
            if existing is not None:
                if existing != amount:
                    raise ResourceBoundError("idempotent reservation changed amount")
                return self.remaining
            if self._used + amount > self.hard_limit:
                raise ResourceExhausted(f"{self.name}:hard_limit_exceeded")
            self._reservations[reservation_id] = amount
            self._used += amount
            return self.remaining


def validate_policy_coverage(limits: Mapping[str, MetricLimit]) -> tuple[str, ...]:
    if not isinstance(limits, Mapping):
        raise ResourceBoundError("limits must be a mapping")
    return tuple(sorted(REQUIRED_METRICS - set(limits)))


def evaluate_summary(guard: ResourceGuard, summary: MeasurementSummary) -> ResourceDecision:
    if summary.metric not in guard.limits:
        raise ResourceBoundError("summary metric is not governed")
    return guard.evaluate(summary.metric, summary.p95)


def evidence_snapshot(guard: ResourceGuard, summaries: Iterable[MeasurementSummary]) -> dict[str, Any]:
    decisions: dict[str, dict[str, Any]] = {}
    for summary in summaries:
        decision = evaluate_summary(guard, summary)
        decisions[summary.metric] = {
            "count": summary.count,
            "minimum": summary.minimum,
            "maximum": summary.maximum,
            "p50": summary.p50,
            "p95": summary.p95,
            "unit": summary.unit,
            "action": decision.action,
            "reason_code": decision.reason_code,
        }
    missing = tuple(sorted(REQUIRED_METRICS - set(decisions)))
    return {
        "policy_version": POLICY_VERSION,
        "complete": not missing,
        "missing_metrics": list(missing),
        "metrics": decisions,
    }
