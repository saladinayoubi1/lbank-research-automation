from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from resource_bounds import (
    DEFAULT_LIMITS,
    POLICY_VERSION,
    REQUIRED_METRICS,
    ConcurrencyBudget,
    MeasurementWindow,
    MetricLimit,
    QuotaBudget,
    ResourceBoundError,
    ResourceExhausted,
    ResourceGuard,
    evidence_snapshot,
    evaluate_summary,
    validate_policy_coverage,
)


def test_frozen_gate19_policy_has_all_required_measurable_surfaces():
    assert set(DEFAULT_LIMITS) == REQUIRED_METRICS
    assert validate_policy_coverage(DEFAULT_LIMITS) == ()
    assert {
        "api_latency_ms",
        "dashboard_latency_ms",
        "ai_chat_timeout_ms",
        "agent_timeout_ms",
        "queue_latency_ms",
        "replay_processing_ms",
        "backtest_runtime_ms",
        "research_runtime_ms",
        "storage_bytes",
        "log_retention_days",
        "runner_concurrency",
        "provider_spend_microusd",
        "provider_tokens",
        "cpu_millis",
        "memory_bytes",
        "job_runtime_ms",
    } == REQUIRED_METRICS


def test_every_metric_has_soft_and_hard_limit_with_explicit_unit():
    for key, limit in DEFAULT_LIMITS.items():
        assert limit.metric == key
        assert limit.unit
        assert limit.soft_limit >= 0
        assert limit.hard_limit >= limit.soft_limit


def test_exact_boundaries_allow_degrade_then_deny_without_bypass():
    guard = ResourceGuard()
    for metric, limit in DEFAULT_LIMITS.items():
        assert guard.evaluate(metric, limit.soft_limit).action == "allow"
        if limit.hard_limit > limit.soft_limit:
            assert guard.evaluate(metric, limit.soft_limit + 1).action == "degrade"
        assert guard.evaluate(metric, limit.hard_limit).action in {"allow", "degrade"}
        denied = guard.evaluate(metric, limit.hard_limit + 1)
        assert denied.action == "deny"
        assert denied.reason_code == "hard_limit_exceeded"
        assert denied.policy_version == POLICY_VERSION
        with pytest.raises(ResourceExhausted, match="hard_limit_exceeded"):
            guard.require_not_exhausted(metric, limit.hard_limit + 1)


def test_unknown_or_incomplete_policy_fails_closed():
    guard = ResourceGuard()
    with pytest.raises(ResourceBoundError, match="unknown"):
        guard.evaluate("unbounded_magic_resource", 1)

    incomplete = dict(DEFAULT_LIMITS)
    incomplete.pop("memory_bytes")
    with pytest.raises(ResourceBoundError, match="complete frozen metric set"):
        ResourceGuard(incomplete)
    assert validate_policy_coverage(incomplete) == ("memory_bytes",)


def test_binary_float_negative_bool_and_invalid_limits_are_rejected():
    guard = ResourceGuard()
    for value in (1.5, -1, True):
        with pytest.raises(ResourceBoundError):
            guard.evaluate("api_latency_ms", value)  # type: ignore[arg-type]
    with pytest.raises(ResourceBoundError):
        MetricLimit("bad", "ms", 10, 9)


def test_measurement_window_produces_deterministic_p50_p95_and_is_bounded():
    window = MeasurementWindow("api_latency_ms", "ms", capacity=5)
    for value in (100, 200, 300, 400, 500):
        window.add(value)
    summary = window.summary()
    assert summary.count == 5
    assert summary.minimum == 100
    assert summary.maximum == 500
    assert summary.p50 == 300
    assert summary.p95 == 500
    with pytest.raises(ResourceExhausted, match="capacity"):
        window.add(600)


def test_measured_p95_drives_resource_decision():
    guard = ResourceGuard()
    window = MeasurementWindow("dashboard_latency_ms", "ms")
    for value in (100, 200, 300, 700, 800):
        window.add(value)
    decision = evaluate_summary(guard, window.summary())
    assert decision.measured == 800
    assert decision.action == "degrade"


def test_runner_concurrency_race_never_exceeds_hard_limit():
    budget = ConcurrencyBudget(2)
    start = threading.Barrier(3)

    def acquire(work_id: str):
        start.wait()
        try:
            return ("allowed", budget.acquire(work_id))
        except ResourceExhausted:
            return ("denied", budget.active)

    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(acquire, ("a", "b", "c")))

    assert sum(status == "allowed" for status, _ in results) == 2
    assert sum(status == "denied" for status, _ in results) == 1
    assert budget.active == 2
    assert max(value for _, value in results) <= 2


def test_concurrency_budget_is_idempotent_for_same_work_and_strict_on_release():
    budget = ConcurrencyBudget(1)
    assert budget.acquire("same") == 1
    assert budget.acquire("same") == 1
    with pytest.raises(ResourceExhausted):
        budget.acquire("other")
    assert budget.release("same") == 0
    with pytest.raises(ResourceBoundError, match="unowned"):
        budget.release("same")


def test_provider_spend_or_token_quota_exhaustion_denies_atomically():
    budget = QuotaBudget(name="provider_tokens", hard_limit=10)
    assert budget.reserve("r1", 7) == 3
    assert budget.reserve("r1", 7) == 3
    with pytest.raises(ResourceBoundError, match="changed amount"):
        budget.reserve("r1", 6)
    with pytest.raises(ResourceExhausted, match="hard_limit_exceeded"):
        budget.reserve("r2", 4)
    assert budget.used == 7
    assert budget.remaining == 3


def test_last_quota_slice_race_has_one_winner_and_no_overspend():
    budget = QuotaBudget(name="provider_spend_microusd", hard_limit=1)
    start = threading.Barrier(2)

    def reserve(reservation_id: str):
        start.wait()
        try:
            budget.reserve(reservation_id, 1)
            return "allowed"
        except ResourceExhausted:
            return "denied"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(reserve, ("a", "b")))

    assert sorted(results) == ["allowed", "denied"]
    assert budget.used == 1
    assert budget.remaining == 0


def test_complete_evidence_snapshot_requires_all_frozen_metrics():
    guard = ResourceGuard()
    summaries = []
    for metric, limit in DEFAULT_LIMITS.items():
        window = MeasurementWindow(metric, limit.unit)
        window.add(limit.soft_limit)
        summaries.append(window.summary())

    evidence = evidence_snapshot(guard, summaries)
    assert evidence["policy_version"] == POLICY_VERSION
    assert evidence["complete"] is True
    assert evidence["missing_metrics"] == []
    assert set(evidence["metrics"]) == REQUIRED_METRICS
    assert all(item["action"] == "allow" for item in evidence["metrics"].values())


def test_incomplete_evidence_snapshot_reports_missing_metrics_instead_of_claiming_complete():
    guard = ResourceGuard()
    window = MeasurementWindow("api_latency_ms", "ms")
    window.add(100)
    evidence = evidence_snapshot(guard, (window.summary(),))
    assert evidence["complete"] is False
    assert "memory_bytes" in evidence["missing_metrics"]
    assert "provider_spend_microusd" in evidence["missing_metrics"]
